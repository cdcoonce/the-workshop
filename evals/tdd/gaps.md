# Gaps

Guarded behaviors that cannot be exercised as a single-prompt case, one line of reason each.
- confirming interface changes and the behaviors to test with the user, and getting plan approval: every case is a single prompt with zero user turns, and T ships a pre-approved plan so the case-agent is never blocked on an approval it cannot get, so no fixture can grade the confirmation step
- deleting production code that was written before its test and redoing it test-first: it only arises after the agent has already broken the Iron Law, which T measures (T1's ordering conjunct) but cannot stage or grade as a recovery in a single prompt
- the refactor step after green, and never refactoring while red: the fixture is small and carries no duplication or shallow module to refactor, and none of T1 to T3 reads a refactor edit
- mocking only at system boundaries and designing interfaces for testability: the fixture is a pure in-process library with no external boundary to mock, so the mocking and interface-design guidance is not exercised
