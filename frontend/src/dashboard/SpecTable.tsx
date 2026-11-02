import { useRef, useState } from 'react';
import Cell from './Cell';
import { icons } from './icons';
import { displayTitle, titleEditable } from './editing';
import type { SpecItem } from './library';
import type { LibraryActions } from './useLibrary';

const RUN_MODES = [['', 'Run'], ['skip', 'Skip'], ['fixme', 'To do']];

// The test cases of one Playwright spec, as an editable table. Every edit rewrites the spec file.
export default function SpecTable({ spec, library }: { spec: SpecItem; library: LibraryActions }) {
  const [newTitle, setNewTitle] = useState('');
  const newTitleRef = useRef<HTMLInputElement>(null);

  function add() {
    if (library.addTest(spec.name, newTitle)) {
      setNewTitle('');
      newTitleRef.current?.focus();
    }
  }

  return (
    <>
      <div className="tablewrap">
        <table className="grid">
          <thead><tr><th className="num">#</th><th>Test case</th><th>Run mode</th><th>Line</th><th></th></tr></thead>
          <tbody>
            {spec.tests.map((test, i) => {
              // "Only" is shown when the file uses it, but is never offered as a choice
              const modes = test.mode === 'only' ? [['only', 'Only (focused)'], ...RUN_MODES] : RUN_MODES;
              return (
                <tr key={i}>
                  <td className="num">{i + 1}</td>
                  <td>
                    <Cell id={`pw|${spec.name}|${i}|title`} value={displayTitle(test)} maxLength={200} label="Test case name"
                          readOnlyReason={titleEditable(test) ? undefined : 'This name has special characters. Edit it in your file.'}
                          onCommit={v => library.editTest(spec.name, i, 'title', v)} />
                  </td>
                  <td>
                    <select className={'cell sel mode-' + (test.mode || 'run')} value={test.mode} aria-label="Run mode"
                            onChange={e => library.editTest(spec.name, i, 'mode', e.target.value)}>
                      {modes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </td>
                  <td className="ln">L{test.line}</td>
                  <td className="rowact">
                    <button className="icon-btn" aria-label={`Delete test case ${i + 1}`} title="Delete this test case"
                            onClick={() => library.deleteTestRow(spec.name, i)}>{icons.trash}</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="draft">
              <td className="num">{icons.plus}</td>
              <td colSpan={3}>
                <input className="cell" ref={newTitleRef} value={newTitle} maxLength={200} aria-label="New test case name"
                       placeholder="Add a test case, for example: user can reset password"
                       onChange={e => setNewTitle(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); add(); } }} />
              </td>
              <td className="rowact"><button className="btn sm" onClick={add}>Add</button></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="tablehint">Edit any cell and it updates straight away. New test cases are added as To do placeholders, so write their steps in your editor.</p>
    </>
  );
}
