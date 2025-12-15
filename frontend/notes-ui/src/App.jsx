import { useEffect, useState } from "react";

const API_URL = "api/notes";

export default function App() {
  const [notes, setNotes] = useState([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  // Function to load notes from the API
  const loadNotes = async () => 
  {
    const res = await fetch(API_URL);
    const data = await res.json();
    setNotes(data);
  }

  // Function to submit a new note to the API
  const submitNote = async () => {
    await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify({title, content})
    });
    setTitle("");
    setContent("");
    loadnotes();
  };

  useEffect(() => {
    loadNotes();

  }, []);


  // Render the UI
  return (
    <div style={{ padding: 20 }}>
      <h1>Live Notes</h1>

      <input
        placeholder="Title"
        value={title}
        onChange={e => setTitle(e.target.value)}
      />

      <br /><br />

      <textarea
        placeholder="Content"
        value={content}
        onChange={e => setContent(e.target.value)}
      />

      <br /><br />

      <button onClick={submitNote}>Save</button>

      <hr />

      <ul>
        {notes.map(n => (
          <li key={n.id}>
            <strong>{n.title}</strong>: {n.content}
          </li>
        ))}
      </ul>
    </div>
  );
}