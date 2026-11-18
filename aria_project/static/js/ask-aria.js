// Ask Aria: posts a question to chatbot:stream and renders the server-sent events.
// Events from chatbot/views.py: sources {sources:[{title, heading, path}]}, token {text},
// done {refused?}, error {message}. All model output is inserted with textContent, never as HTML.
(function () {
  'use strict';

  var form = document.getElementById('ask-form');
  if (!form || !window.fetch || !window.TextDecoder) { return; }

  var conversation = document.getElementById('ask-conversation');
  var input = document.getElementById('ask-message');
  var send = document.getElementById('ask-send');
  var status = document.getElementById('ask-status');
  var streamUrl = form.dataset.streamUrl;
  var helpUrl = form.dataset.helpUrl;
  var helpLabel = form.dataset.helpLabel;
  var csrf = form.querySelector('input[name="csrfmiddlewaretoken"]').value;

  var MSG_UNAVAILABLE = 'Aria is unavailable right now. Please try again later, or contact our team.';
  var MSG_SIGNED_OUT = 'Your session has ended. Please sign in again to keep chatting.';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text) { node.textContent = text; }
    return node;
  }

  function bubble(kind, who) {
    var li = el('li', 'sf-bubble sf-bubble--' + kind);
    li.appendChild(el('p', 'sf-bubble__who', who));
    conversation.appendChild(li);
    li.scrollIntoView({ block: 'nearest' });
    return li;
  }

  function humanHelp(li) {
    var link = el('a', 'btn btn-primary', helpLabel);
    link.href = helpUrl;
    li.appendChild(link);
  }

  function fail(li, text, refused) {
    li.className = 'sf-bubble sf-bubble--refusal';
    var body = li.querySelector('.sf-bubble__text') || li.appendChild(el('p', 'sf-bubble__text'));
    body.textContent = text;
    if (refused !== false) { humanHelp(li); }
  }

  function showSources(li, sources) {
    if (!sources || !sources.length) { return; }
    var wrap = el('div');
    wrap.appendChild(el('p', 'visually-hidden', 'Sources:'));
    var list = el('ul', 'sf-sources');
    list.setAttribute('aria-label', 'Cited sources');
    sources.forEach(function (s) {
      list.appendChild(el('li', 'sf-source', s.heading ? s.title + ' · ' + s.heading : s.title));
    });
    wrap.appendChild(list);
    li.appendChild(wrap);
  }

  function setBusy(busy) {
    send.disabled = busy;
    input.disabled = busy;
    send.textContent = busy ? 'Aria is answering…' : 'Send message';
    status.textContent = busy ? 'Aria is answering.' : '';
  }

  // Parse "event: x\ndata: {...}" blocks; returns the unparsed remainder.
  function drain(buffer, onEvent) {
    var blocks = buffer.split('\n\n');
    var rest = blocks.pop();
    blocks.forEach(function (block) {
      var name = null, data = '';
      block.split('\n').forEach(function (line) {
        if (line.indexOf('event: ') === 0) { name = line.slice(7); }
        else if (line.indexOf('data: ') === 0) { data += line.slice(6); }
      });
      if (!name) { return; }
      try { onEvent(name, JSON.parse(data)); } catch (e) { /* ignore a malformed block */ }
    });
    return rest;
  }

  function ask(question) {
    var userLi = bubble('user', 'You');
    userLi.appendChild(el('p', 'sf-bubble__text', question));

    var li = bubble('assistant', 'Aria · AI assistant');
    var text = el('p', 'sf-bubble__text', 'Looking through Aria’s policies…');
    li.appendChild(text);
    li.setAttribute('aria-busy', 'true');
    setBusy(true);

    var sources = [];
    var started = false;
    var finished = false;

    function onEvent(name, data) {
      if (name === 'sources') {
        sources = data.sources || [];
      } else if (name === 'token') {
        if (!started) { text.textContent = ''; started = true; }
        text.textContent += data.text || '';
      } else if (name === 'done') {
        finished = true;
        if (data.refused) {
          fail(li, text.textContent);
        } else {
          showSources(li, sources);
          li.appendChild(el('p', 'sf-bubble__note', 'Aria explains only. It hasn’t changed any order or refund.'));
        }
      } else if (name === 'error') {
        finished = true;
        fail(li, MSG_UNAVAILABLE);
      }
    }

    return fetch(streamUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'text/event-stream' },
      body: JSON.stringify({ message: question })
    }).then(function (response) {
      if (response.status === 401 || response.status === 403) { fail(li, MSG_SIGNED_OUT, false); return; }
      if (!response.ok || !response.body) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          // 400s carry a user-facing message (empty or too-long question); anything else is an outage
          fail(li, response.status === 400 && body.error ? body.error : MSG_UNAVAILABLE, response.status !== 400);
        });
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';
      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) {
            drain(buffer + '\n\n', onEvent);
            if (!finished) { fail(li, MSG_UNAVAILABLE); }
            return;
          }
          buffer = drain(buffer + decoder.decode(chunk.value, { stream: true }), onEvent);
          return pump();
        });
      }
      return pump();
    }).catch(function () {
      fail(li, MSG_UNAVAILABLE);
    }).then(function () {
      li.removeAttribute('aria-busy');
      setBusy(false);
      input.focus();
    });
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var question = input.value.trim();
    if (!question || send.disabled) { return; }
    input.value = '';
    ask(question);
  });

  // Enter sends, Shift+Enter adds a new line
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true }));
    }
  });
}());
