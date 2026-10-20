"""Create, read, update and delete one review (plus a reply in its subcollection).

    python crud_demo.py

Uses document id "rev-demo", so it never touches the 60 seeded reviews and can be re-run.
Credentials: see firestore_client.py / README.md.
"""
from datetime import datetime, timezone
from pprint import pprint

from firestore_client import COLLECTION, REPLIES, get_db   # first: sets up warning filters
from google.cloud.firestore_v1 import ArrayUnion, Increment

DEMO_ID = 'rev-demo'


def main():
    db = get_db()
    ref = db.collection(COLLECTION).document(DEMO_ID)

    # CREATE: one document with nested maps, arrays and a server timestamp
    ref.set({
        'product': {'sku': 'MASK-001', 'name': 'Low-volume dive mask', 'category': 'Masks & Snorkels'},
        'author': {'account_id': 1, 'username': 'demo.diver', 'verified_purchase': True},
        'order_id': None,
        'rating': 4,
        'ratings': {'quality': 4, 'value': 4, 'fit': 5},
        'title': 'Great seal, slight fogging',
        'body': 'Comfortable on a two-tank dive. Needed defog on the second dive.',
        'tags': ['fit', 'fogging'],
        'photos': [],
        'helpful_votes': 0,
        'status': 'published',
        'created_at': datetime.now(timezone.utc),
    })
    print('CREATE  reviews/rev-demo')

    # READ: fetch it back
    snapshot = ref.get()
    print('READ   ', snapshot.id, '->')
    pprint({k: snapshot.get(k) for k in ('product', 'rating', 'ratings', 'tags', 'helpful_votes')})

    # UPDATE: change a nested field, append to an array, increment a counter (all atomic, server side)
    ref.update({
        'ratings.value': 5,                       # dotted path updates one key inside the map
        'tags': ArrayUnion(['travel']),           # adds only if not already present
        'helpful_votes': Increment(1),            # no read-modify-write race
        'edited_at': datetime.now(timezone.utc),  # new field: no schema change needed
    })
    # ...and add a staff reply in the replies subcollection
    reply_ref = ref.collection(REPLIES).document('reply-1')
    reply_ref.set({'author_role': 'staff', 'author': 'staff01',
                   'body': 'Thanks! A drop of defog before each dive fixes the fogging.',
                   'created_at': datetime.now(timezone.utc)})
    after = ref.get()
    print('UPDATE  ratings.value =', after.get('ratings.value'), '| tags =', after.get('tags'),
          '| helpful_votes =', after.get('helpful_votes'))
    print('        replies:', [r.get('body') for r in ref.collection(REPLIES).stream()])

    # DELETE: Firestore does not cascade, so delete the subcollection first, then the review
    for reply in ref.collection(REPLIES).stream():
        reply.reference.delete()
    ref.delete()
    print('DELETE  reviews/rev-demo exists afterwards?', ref.get().exists,
          '| replies left:', len(list(ref.collection(REPLIES).stream())))


if __name__ == '__main__':
    main()
