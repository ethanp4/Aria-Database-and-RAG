import json
from unittest import mock
from urllib.error import URLError

from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Account
from chatbot import views
from orders.tests.test_views import login

URL = reverse('chatbot:stream')
SUPPORT = 'rag/documents/support/'


def make_account(username, role='user'):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


def chunk(path='rag/documents/shared/returns-and-refunds.md', similarity=0.8, title='Returns and refunds'):
    return {'source_path': path, 'title': title, 'heading': 'Returns',
            'content': 'Items can be returned within 30 days.', 'similarity': similarity}


def post(client, message='How do I return an item?'):
    return client.post(URL, data=json.dumps({'message': message}), content_type='application/json')


def events(response):
    """Parse an SSE response into [(event, data), ...]."""
    body = b''.join(response.streaming_content).decode('utf-8')
    parsed = []
    for block in body.strip().split('\n\n'):
        lines = dict(line.split(': ', 1) for line in block.splitlines())
        parsed.append((lines['event'], json.loads(lines['data'])))
    return parsed


class FakeOllamaStream:
    """Stands in for urlopen() on /api/chat: yields NDJSON lines like Ollama does."""

    def __init__(self, pieces):
        lines = [{'message': {'content': p}, 'done': False} for p in pieces]
        lines.append({'message': {'content': ''}, 'done': True})
        self.lines = [json.dumps(line).encode('utf-8') + b'\n' for line in lines]

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, *exc):
        return False


@mock.patch.object(views, '_embed_question', return_value=[0.0] * 384)
class ChatStreamRequestTests(TestCase):
    def setUp(self):
        self.customer = make_account('cust1')

    def test_anonymous_gets_401(self, _embed):
        self.assertEqual(post(self.client).status_code, 401)

    def test_get_not_allowed(self, _embed):
        login(self.client, self.customer)
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_rejects_bad_payloads(self, _embed):
        login(self.client, self.customer)
        bad_json = self.client.post(URL, data='not json', content_type='application/json')
        self.assertEqual(bad_json.status_code, 400)
        self.assertEqual(post(self.client, '   ').status_code, 400)
        self.assertEqual(post(self.client, 'x' * (views.MAX_QUESTION_LENGTH + 1)).status_code, 400)

    def test_csrf_token_required(self, _embed):
        client = Client(enforce_csrf_checks=True)
        login(client, self.customer)
        self.assertEqual(post(client).status_code, 403)

    def test_ollama_unavailable_returns_503(self, embed):
        embed.side_effect = URLError('connection refused')
        login(self.client, self.customer)
        self.assertEqual(post(self.client).status_code, 503)


@mock.patch.object(views, '_embed_question', return_value=[0.0] * 384)
class RoleScopingTests(TestCase):
    def test_customer_cannot_retrieve_support_documents(self, _embed):
        self.assertNotIn(SUPPORT, views.allowed_source_prefixes(make_account('cust1')))

    def test_staff_and_admin_can_retrieve_support_documents(self, _embed):
        self.assertIn(SUPPORT, views.allowed_source_prefixes(make_account('staff1', 'staff')))
        self.assertIn(SUPPORT, views.allowed_source_prefixes(make_account('admin1', 'admin')))

    def test_customer_search_is_scoped_and_leaked_rows_are_dropped(self, _embed):
        customer = make_account('cust1')
        leaked = chunk(path=SUPPORT + 'refund-decision-guide.md', title='Refund decision guide')
        with mock.patch.object(views, '_search_chunks', return_value=[chunk(), leaked]) as search:
            sources = views._retrieve_sources('refund?', customer)
        self.assertNotIn(SUPPORT, search.call_args.args[1])
        self.assertEqual([s['title'] for s in sources], ['Returns and refunds'])


@mock.patch.object(views, '_embed_question', return_value=[0.0] * 384)
@override_settings(ARIA_RAG_MIN_SIMILARITY=0.35)
class RefusalTests(TestCase):
    """Invariant 6: no relevant source -> refuse, offer a human, never call the model."""

    def setUp(self):
        login(self.client, make_account('cust1'))

    def assert_refused(self, response):
        self.assertEqual(response.status_code, 200)
        parsed = events(response)
        self.assertEqual(parsed[0], ('sources', {'sources': []}))
        self.assertEqual(parsed[1], ('token', {'text': views.REFUSAL}))
        self.assertEqual(parsed[2], ('done', {'refused': True}))
        self.assertIn('support team', views.REFUSAL)

    @mock.patch.object(views, 'urlopen')
    def test_refuses_when_index_returns_nothing(self, chat_urlopen, _embed):
        with mock.patch.object(views, '_search_chunks', return_value=[]):
            self.assert_refused(post(self.client, 'What is the capital of France?'))
        chat_urlopen.assert_not_called()

    @mock.patch.object(views, 'urlopen')
    def test_refuses_when_best_match_is_below_threshold(self, chat_urlopen, _embed):
        weak = [chunk(similarity=0.32), chunk(similarity=0.10)]
        with mock.patch.object(views, '_search_chunks', return_value=weak):
            self.assert_refused(post(self.client, 'Can you recommend a stock to buy?'))
        chat_urlopen.assert_not_called()

    @mock.patch.object(views, 'urlopen', return_value=FakeOllamaStream(['Within ', '30 days [Returns and refunds].']))
    def test_relevant_source_streams_answer_with_citations(self, _chat, _embed):
        with mock.patch.object(views, '_search_chunks', return_value=[chunk(similarity=0.63), chunk(similarity=0.2)]):
            parsed = events(post(self.client))
        self.assertEqual(parsed[0][0], 'sources')
        self.assertEqual([s['title'] for s in parsed[0][1]['sources']], ['Returns and refunds'])
        self.assertEqual([e for e, _ in parsed], ['sources', 'token', 'token', 'done'])
        self.assertEqual(''.join(d['text'] for e, d in parsed if e == 'token'),
                         'Within 30 days [Returns and refunds].')

    @mock.patch.object(views, 'urlopen', side_effect=URLError('model crashed'))
    def test_model_failure_mid_request_emits_error_event(self, _chat, _embed):
        with mock.patch.object(views, '_search_chunks', return_value=[chunk()]):
            parsed = events(post(self.client))
        self.assertEqual([e for e, _ in parsed], ['sources', 'error'])


class PgvectorSearchTests(TestCase):
    """Runs the real SQL against pgvector (skipped where the extension isn't installed)."""

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            if cursor.fetchone() is None:
                self.skipTest('pgvector not available on this PostgreSQL server')

        def one_hot(i):
            v = [0.0] * 384
            v[i] = 1.0
            return json.dumps(v)

        with connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector')
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rag_document_chunks (
                    source_path TEXT NOT NULL, chunk_index INTEGER NOT NULL, title TEXT NOT NULL,
                    heading TEXT NOT NULL, content TEXT NOT NULL, document_hash TEXT NOT NULL,
                    embedding VECTOR(384) NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (source_path, chunk_index))
            """)
            cursor.execute('DELETE FROM rag_document_chunks')
            for path, title, vec in [
                ('rag/documents/shared/returns.md', 'Returns', one_hot(0)),
                (SUPPORT + 'refund-decision-guide.md', 'Refund decision guide', one_hot(0)),
                ('rag/documents/customer/catalogue.md', 'Catalogue', one_hot(1)),
            ]:
                cursor.execute(
                    "INSERT INTO rag_document_chunks VALUES (%s, 0, %s, '', 'text', 'h', %s::vector, now())",
                    [path, title, vec])
        self.query = [1.0] + [0.0] * 383

    def titles_for(self, account):
        with mock.patch.object(views, '_embed_question', return_value=self.query):
            return [s['title'] for s in views._retrieve_sources('refund?', account)]

    def test_customer_never_gets_support_chunks(self):
        self.assertEqual(self.titles_for(make_account('cust1')), ['Returns'])

    def test_staff_gets_support_chunks(self):
        self.assertEqual(sorted(self.titles_for(make_account('staff1', 'staff'))),
                         ['Refund decision guide', 'Returns'])
