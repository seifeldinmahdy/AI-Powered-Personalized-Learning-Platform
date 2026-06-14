/**
 * Auth left-panel preview cards — Slides / Knowledge Check / Exercises.
 * Static marketing specimens ported verbatim from personifai-design/01-auth.jsx.
 * These are illustrative only (no live data).
 */

export function SlidePreviewCard() {
  return (
    <div style={{ width: '100%', background: '#FBF8F1', border: '1px solid #D4CCBA', borderRadius: 12, boxShadow: '0 16px 40px -16px rgba(26,22,17,0.28)', padding: '22px 24px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <span style={{ fontFamily: 'var(--ff-mono)', fontSize: 10.5, letterSpacing: '0.1em', color: '#9A9080' }}>SLIDE 07 / 24</span>
        <span style={{ fontFamily: 'var(--ff-mono)', fontSize: 9.5, letterSpacing: '0.1em', color: '#9A9080' }}>INTERMEDIATE</span>
      </div>
      <div style={{ fontFamily: 'var(--ff-display)', fontWeight: 700, fontSize: 22, color: '#1A1611', letterSpacing: '-0.025em', lineHeight: 1.1, marginBottom: 14 }}>Base cases and termination</div>
      <div style={{ borderLeft: '2px solid #2563EB', paddingLeft: 12, marginBottom: 12 }}>
        <div style={{ fontFamily: 'var(--ff-mono)', fontSize: 9.5, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#2563EB', marginBottom: 4 }}>DEFINE · BASE CASE</div>
        <div style={{ fontFamily: 'var(--ff-body)', fontSize: 12.5, color: '#1A1611', lineHeight: 1.5 }}>The smallest input for which a function returns directly without making a further recursive call.</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 12 }}>
        {['Every recursive function must reach a base case to terminate.', 'Without one, the call stack fills and throws an overflow error.', 'The base case acts as the stopping condition of the recursion.'].map((b, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <span style={{ width: 4, height: 4, background: '#6E665A', borderRadius: '50%', flexShrink: 0, marginTop: 5 }} />
            <span style={{ fontFamily: 'var(--ff-body)', fontSize: 12, color: '#6E665A', lineHeight: 1.45 }}>{b}</span>
          </div>
        ))}
      </div>
      <div style={{ background: '#13100D', borderRadius: 6, padding: '12px 14px', fontFamily: 'var(--ff-mono)', fontSize: 10.5, lineHeight: 1.65, marginBottom: 14 }}>
        <div><span style={{ color: '#FF7B72' }}>def</span> <span style={{ color: '#D2A8FF' }}>factorial</span>(n):</div>
        <div><span style={{ color: '#6E7793' }}>{'  '}# base case — stops recursion</span></div>
        <div>{'  '}<span style={{ color: '#FF7B72' }}>if</span> n {'<='} <span style={{ color: '#FFA657' }}>1</span>: <span style={{ color: '#FF7B72' }}>return</span> <span style={{ color: '#FFA657' }}>1</span></div>
        <div>{'  '}<span style={{ color: '#FF7B72' }}>return</span> n * <span style={{ color: '#D2A8FF' }}>factorial</span>(n - <span style={{ color: '#FFA657' }}>1</span>)</div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--ff-mono)', fontSize: 10, color: '#9A9080', letterSpacing: '0.06em' }}>
        <span>← PREVIOUS</span><span>07 / 24</span><span>NEXT →</span>
      </div>
    </div>
  );
}

export function KnowledgeCheckCard() {
  return (
    <div style={{ width: '100%', background: '#FBF8F1', border: '1px solid #D4CCBA', borderRadius: 12, boxShadow: '0 16px 40px -16px rgba(26,22,17,0.28)', padding: '22px 24px' }}>
      <div style={{ marginBottom: 4 }}>
        <div style={{ fontFamily: 'var(--ff-mono)', fontSize: 10.5, letterSpacing: '0.08em', color: '#9A9080' }}>KNOWLEDGE CHECK · SLIDE 07</div>
        <div style={{ fontFamily: 'var(--ff-mono)', fontSize: 9.5, letterSpacing: '0.06em', color: '#9A9080', marginTop: 2 }}>QUESTION 02 OF 04</div>
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 12, marginBottom: 16 }}>
        {[true, true, 'active', false].map((d, i) => (
          <div key={i} style={{ width: d === 'active' ? 20 : 8, height: 8, borderRadius: 4, background: d === false ? 'transparent' : '#2563EB', border: d === false ? '1px solid #C8C0B0' : 'none' }} />
        ))}
      </div>
      <div style={{ fontFamily: 'var(--ff-display)', fontWeight: 500, fontSize: 16, color: '#1A1611', lineHeight: 1.4, marginBottom: 18 }}>A recursive function calls itself with n–1 but never checks the value of n. What happens when n reaches 0?</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
        {[
          { l: 'A', text: 'It returns 0 because the integer is falsy.' },
          { l: 'B', text: 'It continues to call itself, eventually causing a stack overflow.', selected: true },
          { l: 'C', text: 'Python automatically inserts a return statement at n = 0.' },
          { l: 'D', text: 'The function raises a ValueError by default.' },
        ].map((opt) => (
          <div key={opt.l} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', border: `1px solid ${opt.selected ? '#2563EB' : '#D4CCBA'}`, borderLeft: `${opt.selected ? 3 : 1}px solid ${opt.selected ? '#2563EB' : '#D4CCBA'}`, borderRadius: 6, background: opt.selected ? 'rgba(37,99,235,0.04)' : 'transparent' }}>
            <span style={{ fontFamily: 'var(--ff-mono)', fontSize: 10.5, color: opt.selected ? '#2563EB' : '#9A9080', width: 12, flexShrink: 0 }}>{opt.l}</span>
            <span style={{ fontFamily: 'var(--ff-body)', fontSize: 12.5, color: opt.selected ? '#1A1611' : '#6E665A', fontWeight: opt.selected ? 500 : 400, flex: 1, lineHeight: 1.4 }}>{opt.text}</span>
            {opt.selected && <span style={{ width: 8, height: 8, background: '#2563EB', borderRadius: 1, flexShrink: 0 }} />}
          </div>
        ))}
      </div>
      <button style={{ width: '100%', background: '#2563EB', color: '#fff', border: 'none', borderRadius: 6, padding: '14px', fontFamily: 'var(--ff-body)', fontWeight: 500, fontSize: 12.5, letterSpacing: '0.1em', textTransform: 'uppercase', cursor: 'default' }}>SUBMIT ANSWER →</button>
    </div>
  );
}

export function ExercisesCard() {
  const codeFont = 'var(--ff-mono)';
  return (
    <div style={{ width: '100%', background: '#FBF8F1', border: '1px solid #D4CCBA', borderRadius: 12, boxShadow: '0 16px 40px -16px rgba(26,22,17,0.28)', padding: '22px 24px' }}>
      <div style={{ fontFamily: codeFont, fontSize: 10.5, letterSpacing: '0.08em', color: '#9A9080' }}>EXERCISES · SESSION 05</div>
      <div style={{ fontFamily: codeFont, fontSize: 10, color: '#6E665A', marginTop: 4, marginBottom: 16 }}>// 4 problems · 1 of 4 done</div>
      {/* Row 1 — solved */}
      <div style={{ borderTop: '2px solid #16A34A', padding: '12px 0', borderBottom: '1px solid #D4CCBA' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontFamily: codeFont, fontSize: 9.5, letterSpacing: '0.12em', color: '#16A34A', fontWeight: 600 }}>01 · SOLVED</span>
          <span style={{ fontFamily: codeFont, fontSize: 9.5, color: '#9A9080' }}>EASY</span>
        </div>
        <div style={{ fontFamily: 'var(--ff-body)', fontSize: 12.5, color: '#6E665A', lineHeight: 1.4 }}>Write the base case for <code style={{ fontFamily: codeFont, fontSize: 11, background: 'rgba(0,0,0,0.06)', padding: '1px 4px', borderRadius: 3 }}>countdown(n)</code>.</div>
      </div>
      {/* Row 2 — active */}
      <div style={{ borderLeft: '3px solid #2563EB', padding: '12px 0 12px 12px', borderBottom: '1px solid #D4CCBA' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontFamily: codeFont, fontSize: 9.5, letterSpacing: '0.12em', color: '#2563EB', fontWeight: 600 }}>02 · ACTIVE</span>
          <span style={{ fontFamily: codeFont, fontSize: 9.5, color: '#9A9080' }}>EASY</span>
        </div>
        <div style={{ fontFamily: 'var(--ff-body)', fontSize: 12.5, color: '#1A1611', lineHeight: 1.4, marginBottom: 10 }}>Complete <code style={{ fontFamily: codeFont, fontSize: 11, background: 'rgba(0,0,0,0.06)', padding: '1px 4px', borderRadius: 3 }}>factorial</code> so that <code style={{ fontFamily: codeFont, fontSize: 11, background: 'rgba(0,0,0,0.06)', padding: '1px 4px', borderRadius: 3 }}>factorial(5)</code> returns 120.</div>
        <div style={{ background: '#13100D', borderRadius: 5, padding: '10px 12px', fontFamily: codeFont, fontSize: 10.5, lineHeight: 1.6, marginBottom: 8 }}>
          <div><span style={{ color: '#FF7B72' }}>def</span> <span style={{ color: '#D2A8FF' }}>factorial</span>(n):</div>
          <div>{'  '}<span style={{ color: '#FF7B72' }}>if</span> n {'<='} <span style={{ color: '#FFA657' }}>1</span>: <span style={{ color: '#FF7B72' }}>return</span> <span style={{ color: '#FFA657' }}>1</span></div>
          <div>{'  '}<span style={{ color: '#FF7B72' }}>return</span> n * <span style={{ borderBottom: '1px solid #6E7793', color: '#6E7793' }}>___________</span></div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
          <input readOnly style={{ width: 56, padding: '5px 8px', fontFamily: codeFont, fontSize: 11, border: '1px solid #D4CCBA', borderRadius: 4, background: 'transparent', color: '#1A1611', outline: 'none' }} defaultValue="1" />
          <button style={{ background: '#2563EB', color: '#fff', border: 'none', borderRadius: 4, padding: '5px 12px', fontFamily: 'var(--ff-body)', fontWeight: 500, fontSize: 11, letterSpacing: '0.08em', cursor: 'default' }}>RUN</button>
        </div>
        <div style={{ fontFamily: codeFont, fontSize: 10, color: '#16A34A' }}>// ✓ output: 120 · expected: 120</div>
      </div>
      {/* Row 3 — locked */}
      <div style={{ padding: '12px 0', opacity: 0.45 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontFamily: codeFont, fontSize: 9.5, letterSpacing: '0.12em', color: '#9A9080', fontWeight: 600 }}>03 · LOCKED</span>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ fontFamily: codeFont, fontSize: 9.5, color: '#9A9080' }}>MEDIUM</span>
            <svg width="10" height="12" viewBox="0 0 10 12" fill="none"><rect x="1" y="5" width="8" height="7" rx="1" stroke="#9A9080" strokeWidth="1.2" /><path d="M3 5V3.5a2 2 0 0 1 4 0V5" stroke="#9A9080" strokeWidth="1.2" strokeLinecap="round" /></svg>
          </div>
        </div>
        <div style={{ fontFamily: 'var(--ff-body)', fontSize: 12.5, color: '#9A9080', lineHeight: 1.4 }}>Fix the infinite recursion in <code style={{ fontFamily: codeFont, fontSize: 11, background: 'rgba(0,0,0,0.06)', padding: '1px 4px', borderRadius: 3 }}>sum_to(n)</code>.</div>
      </div>
    </div>
  );
}
