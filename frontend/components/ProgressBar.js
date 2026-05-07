export default function ProgressBar({ progress = 0, currentStep = "", logs = [] }) {
  return (
    <section style={{ margin: "1.5rem 0" }}>
      <h2>Generation Progress</h2>
      <div style={{ width: "100%", background: "#ddd", height: "16px", borderRadius: "999px", overflow: "hidden" }}>
        <div style={{ width: `${progress}%`, background: "#0e7490", height: "100%" }} />
      </div>
      <p>{progress}% - {currentStep}</p>
      <ul>
        {logs.map((log, index) => (
          <li key={`${log}-${index}`}>{log}</li>
        ))}
      </ul>
    </section>
  );
}
