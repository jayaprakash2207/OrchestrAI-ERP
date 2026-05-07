export default function FileDownload({ files = [], downloadAllUrl = null }) {
  return (
    <section>
      <h2>Generated Files</h2>
      <ul>
        {files.map((file) => (
          <li key={file.name}>
            {file.name} ({file.size}) {downloadAllUrl ? <a href={downloadAllUrl}>Download</a> : <button type="button">Download</button>}
          </li>
        ))}
      </ul>
      {downloadAllUrl ? <a href={downloadAllUrl}>Download All Files</a> : <button type="button">Download All Files</button>}
    </section>
  );
}
