/**
 * GSAP motion helpers for theory (short-answer) deliverable workspace.
 * Requires global gsap (vendor/gsap.min.js).
 */
(function initTheoryMotion(global) {
  let theoryCtx = null;

  function prefersReducedMotion() {
    return global.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function killTheoryMotion() {
    if (theoryCtx) {
      theoryCtx.revert();
      theoryCtx = null;
    }
  }

  function animateTheoryWorkspaceEnter(gridEl, cards, contentCol) {
    killTheoryMotion();
    if (!global.gsap || !gridEl || prefersReducedMotion()) return;

    const gsap = global.gsap;
    const staggerTargets = Array.isArray(cards) ? cards.slice(0, cards.length > 5 ? 3 : cards.length) : [];

    theoryCtx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: 'power1.out' } });
      tl.fromTo(
        contentCol || '.deliverable-content-col',
        { autoAlpha: 0, y: 6 },
        { autoAlpha: 1, y: 0, duration: 0.2 },
        0,
      );
      if (staggerTargets.length) {
        tl.from(
          staggerTargets,
          { autoAlpha: 0, y: 8, stagger: 0.04, duration: 0.18 },
          0.08,
        );
      }
    }, gridEl);
  }

  function animateTheoryTabSwitch(bodyEl) {
    if (!global.gsap || !bodyEl || prefersReducedMotion()) return;
    global.gsap.fromTo(
      bodyEl,
      { autoAlpha: 0, y: 4 },
      { autoAlpha: 1, y: 0, duration: 0.18, overwrite: 'auto' },
    );
  }

  global.TheoryMotion = {
    killTheoryMotion,
    animateTheoryWorkspaceEnter,
    animateTheoryTabSwitch,
  };
}(window));
