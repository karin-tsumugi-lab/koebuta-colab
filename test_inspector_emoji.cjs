// Exercise insertion after a textarea change has replaced the original DOM node.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('Koebuta_Scenario_Inspector_v0.1.6.html', 'utf8');
new vm.Script(html.slice(html.indexOf('<script>') + 8, html.indexOf('</script>')));
const catalog = JSON.parse(html.match(/const EMOTIONS = (\{[\s\S]*?\n\});/)[1]);
assert.equal(Object.keys(catalog).length, 34);
assert.equal(catalog.worried[1], '😟');
const listeners = {};
let button;
let saved;
const context = {
  EVENT_TAGS: ['🤭'],
  byId: () => ({addEventListener: (name, handler) => { listeners[name] = handler; }}),
  document: {
    createElement: (type) => {
      const element = {append() {}, setAttribute() {}, value: '🤭'};
      if (type === 'button') button = element;
      return element;
    },
    querySelector: () => ({append() {}}),
  },
  alert: (message) => { throw new Error(message); },
  commitField: (index, field, value) => { saved = {index, field, value}; },
};
const source = html.slice(html.indexOf('let eventTarget=null;'), html.indexOf("byId('search').addEventListener"));
vm.runInNewContext(source, context);
const textarea = {dataset: {field: 'tts_text', idx: '0'}, value: '確認した文章です。',
  selectionStart: 3, selectionEnd: 3, readOnly: false};
listeners.input({target: textarea});
textarea.value = '再描画で置き換えられた古い要素';
textarea.isConnected = false;
button.onclick();
assert.deepEqual(saved, {index: 0, field: 'tts_text', value: '確認し🤭た文章です。'});
console.log('Inspector emoji insertion passed');
