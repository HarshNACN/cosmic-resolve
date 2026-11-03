import { useEffect, useState } from "react";

const API = "http://localhost:8000";

// Placeholder shell. T21 replaces this with case queue / proposal card / trace pane.
export default function App() {
  const [cases, setCases] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API}/cases`)
      .then((r) => r.json())
      .then(setCases)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: 24 }}>
      <h1>Cosmic Resolve</h1>
      {error && <p>Backend unreachable: {error}</p>}
      <ul>
        {cases.map((c) => (
          <li key={c.case_id}>
            {c.case_id} - {c.case_type}
          </li>
        ))}
      </ul>
    </main>
  );
}
