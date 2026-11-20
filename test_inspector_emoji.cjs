// Exercise insertion after a textarea change has replaced the original DOM node.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('Koebuta_Scenario_Inspector_v3.html', 'utf8');
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

const reviewDoc = {
  schema_version: 1,
  speakers: {n: {name: '朗読者', kind: 'narrator'}},
  segments: [{
    id: 't0001', speaker_id: 'n', emotion: 'neutral',
    text: '｜明日《あす》の朝、冷い川のほとりを歩きます。',
    notes: ['初稿'],
    koebuta_added_ruby: [{start: 11, end: 13, surface: '冷い', reading: 'つめたい', selection: 'auto'}],
  }],
};
reviewDoc.segments[0].koebuta_added_ruby[0].start = reviewDoc.segments[0].text.indexOf('冷い');
reviewDoc.segments[0].koebuta_added_ruby[0].end = reviewDoc.segments[0].koebuta_added_ruby[0].start + 2;
const state = {doc: reviewDoc};
let edits = 0;
Object.assign(context, {
  state,
  clone: structuredClone,
  change: (next) => { state.doc = next; edits++; },
});
const editSource = html.slice(html.indexOf("byId('rows').addEventListener('change'"),
  html.indexOf("byId('rows').addEventListener('click'"));
vm.runInNewContext(editSource, context);
const note = {dataset: {note: '0:0'}, value: '[効果音] この発話の直後に水音'};
const choice = {dataset: {rubyChoice: '0:0'}, value: 'kana'};
for (const name of ['focusin', 'input', 'keyup', 'mouseup', 'select']) {
  listeners[name]({target: note});
  listeners[name]({target: choice});
}
assert.equal(edits, 0);
listeners.change({target: note});
listeners.change({target: choice});
assert.equal(edits, 2);
assert.equal(state.doc.segments[0].notes[0], note.value);
assert.equal(state.doc.segments[0].koebuta_added_ruby[0].selection, 'kana');
if (process.env.KOEBUTA_INSPECTOR_TEST_EXPORT) {
  fs.writeFileSync(process.env.KOEBUTA_INSPECTOR_TEST_EXPORT, JSON.stringify(state.doc));
}
