// Shows only the policy clause identifiers the proposal cites. The current API does not return clause
// text, so none is shown and none is invented.
export default function PolicyBasis({ state }) {
  const ids = state.status === "ready" && Array.isArray(state.data?.proposal?.policy_clause_ids)
    ? state.data.proposal.policy_clause_ids
    : null;

  return (
    <section className="panel" aria-labelledby="policy-heading">
      <h2 id="policy-heading">Policy basis</h2>
      {ids === null ? (
        <p>
          {state.status === "ready"
            ? "This run did not produce a proposal, so no policy clauses are cited."
            : "Generate a recommendation to see cited policy."}
        </p>
      ) : ids.length === 0 ? (
        <p>The proposal did not cite any policy clause.</p>
      ) : (
        <>
          <h3>Cited policy clause IDs</h3>
          <ul className="clause-list">
            {ids.map((id) => (
              <li key={id}>
                <code>{id}</code>
              </li>
            ))}
          </ul>
          <p className="muted">Policy text is unavailable from this service. The clause IDs above identify it.</p>
        </>
      )}
    </section>
  );
}
