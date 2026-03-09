import { useMemo, useState, useRef, useEffect } from 'react';

const API_BASE = '/api';
const SUPPORTED = '.txt,.md,.pdf,.doc,.docx,.csv,.png,.jpg,.jpeg,.webp';

const EXAMPLE_QUESTIONS = [
  "What are the key points in the documents?",
  "Summarize the main findings",
  "What insights can you provide?",
  "Explain the technical details"
];

async function readApiResponse(res) {
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return res.json();
  return { detail: await res.text() };
}

function Sources({ sources }) {
  if (!sources?.length) return null;
  return (
    <div className="sources">
      {sources.map((s, i) => (
        <span key={`${s.source}-${i}`} className="chip">
          {s.source} ({Number(s.score || 0).toFixed(2)})
        </span>
      ))}
    </div>
  );
}

function ChatMessage({ role, content, sources }) {
  return (
    <div className={`msg ${role}`}>
      {role === 'assistant' && <div className="botName">Zill</div>}
      <div className="bubble">
        <p>{content}</p>
        {role === 'assistant' ? <Sources sources={sources} /> : null}
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState('chat');
  const [chats, setChats] = useState([{ id: 1, title: 'New Chat', messages: [] }]);
  const [activeChat, setActiveChat] = useState(1);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const chatEndRef = useRef(null);

  const [filesToIndex, setFilesToIndex] = useState([]);
  const [indexResult, setIndexResult] = useState([]);
  const [indexBusy, setIndexBusy] = useState(false);

  const currentChat = chats.find((c) => c.id === activeChat) || chats[0];
  const history = currentChat.messages;
  const canSend = useMemo(() => question.trim().length > 1 && !busy, [question, busy]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  function newChat() {
    const newId = Math.max(...chats.map((c) => c.id)) + 1;
    setChats([...chats, { id: newId, title: 'New Chat', messages: [] }]);
    setActiveChat(newId);
    setPage('chat');
  }

  function deleteChat(id) {
    if (chats.length === 1) return;
    const filtered = chats.filter((c) => c.id !== id);
    setChats(filtered);
    if (activeChat === id) setActiveChat(filtered[0].id);
  }

  async function uploadFile(f, idx) {
    void idx;
    const fd = new FormData();
    fd.append('file', f);
    const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: fd });
    const data = await readApiResponse(res);
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    return data;
  }

  async function uploadAndIndex() {
    setIndexBusy(true);
    setIndexResult([]);
    try {
      const output = [];
      for (let i = 0; i < filesToIndex.length; i += 1) {
        const data = await uploadFile(filesToIndex[i], i);
        output.push(data);
      }
      setIndexResult(output);
      setFilesToIndex([]);
    } catch (err) {
      setIndexResult([{ filename: 'error', chunks_indexed: 0, error: String(err.message || err) }]);
    } finally {
      setIndexBusy(false);
    }
  }

  async function sendMessage() {
    const q = question.trim();
    if (!q) return;

    setBusy(true);
    setQuestion('');

    const userMsg = { role: 'user', content: file ? `${q} (file: ${file.name})` : q };
    const historyForApi = history.map((m) => ({ role: m.role, content: m.content }));

    setChats((prev) =>
      prev.map((c) =>
        c.id === activeChat
          ? {
              ...c,
              messages: [...c.messages, userMsg],
              title: c.messages.length === 0 ? q.slice(0, 30) : c.title,
            }
          : c
      )
    );

    try {
      const fd = new FormData();
      fd.append('question', q);
      fd.append('history_json', JSON.stringify(historyForApi));

      if (file) {
        fd.append('file', file);
      }

      const res = await fetch(`${API_BASE}/chat`, { method: 'POST', body: fd });
      const data = await readApiResponse(res);
      if (!res.ok) throw new Error(data.detail || 'Failed');

      setChats((prev) =>
        prev.map((c) =>
          c.id === activeChat
            ? { ...c, messages: [...c.messages, { role: 'assistant', content: data.answer, sources: data.sources || [] }] }
            : c
        )
      );
      setFile(null);
    } catch (err) {
      setChats((prev) =>
        prev.map((c) =>
          c.id === activeChat
            ? { ...c, messages: [...c.messages, { role: 'assistant', content: `Error: ${String(err.message || err)}`, sources: [] }] }
            : c
        )
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebarHeader">
          <h2>💬 Conversations</h2>
          <button onClick={newChat} className="newChatBtn">+</button>
        </div>

        <div className="chatList">
          {chats.map((chat) => (
            <div
              key={chat.id}
              className={`chatItem ${activeChat === chat.id && page === 'chat' ? 'active' : ''}`}
              onClick={() => {
                setActiveChat(chat.id);
                setPage('chat');
              }}
            >
              <span className="chatTitle">{chat.title}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteChat(chat.id);
                }}
                className="deleteBtn"
              >
                🗑️
              </button>
            </div>
          ))}
        </div>

        <div className="sidebarFooter">
          <button className={`navBtn ${page === 'index' ? 'active' : ''}`} onClick={() => setPage('index')}>
            📁 Index Files
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="header">
          <button className="menuBtn" onClick={() => setSidebarOpen(!sidebarOpen)}>menu</button>
          <h1>✨ KnowledgeHub</h1>
        </header>

        {page === 'chat' ? (
          <>
            <div className="chatWindow">
              {history.length === 0 ? (
                <div className="emptyState">
                  <div className="emptyIcon">✨</div>
                  <h3>Welcome to KnowledgeHub</h3>
                  <p>Your intelligent document assistant</p>
                  <div className="exampleQuestions">
                    <p className="exampleLabel">Try asking:</p>
                    {EXAMPLE_QUESTIONS.map((q, i) => (
                      <button key={i} className="exampleBtn" onClick={() => setQuestion(q)}>
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {history.map((m, i) => <ChatMessage key={i} role={m.role} content={m.content} sources={m.sources} />)}
              {busy && (
                <div className="msg assistant">
                  <div className="botName">Zill</div>
                  <div className="bubble">
                    <div className="loader">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className="inputArea">
              {file ? <div className="fileChip">📎 {file.name} <button onClick={() => setFile(null)}>✕</button></div> : null}
              <div className="chatInput">
                <label className="fileBtn">
                  📎
                  <input type="file" accept={SUPPORTED} onChange={(e) => setFile(e.target.files?.[0] || null)} style={{ display: 'none' }} />
                </label>
                <textarea
                  rows={1}
                  placeholder="Type your message..."
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage();
                    }
                  }}
                />
                <button onClick={sendMessage} disabled={!canSend} className="sendBtn">{busy ? '⏳' : '➤'}</button>
              </div>
            </div>
          </>
        ) : (
          <div className="indexPage">
            <button className="closeBtn" onClick={() => setPage('chat')}>✕</button>
            <div className="indexCard">
              <h2>📁 Index Files</h2>
              <p>Upload files to add them to vector index. Tags are auto-generated.</p>

              <input type="file" multiple accept={SUPPORTED} onChange={(e) => setFilesToIndex(Array.from(e.target.files || []))} className="fileInput" />

              {filesToIndex.length > 0 ? (
                <div className="fileList">
                  {filesToIndex.map((f, i) => <div key={i} className="fileItem">{f.name}</div>)}
                </div>
              ) : null}

              <button onClick={uploadAndIndex} disabled={filesToIndex.length === 0 || indexBusy} className="indexBtn">
                {indexBusy ? 'Indexing...' : 'Upload and Index'}
              </button>

              {indexResult.length > 0 ? (
                <div className="result">
                  {indexResult.map((row, idx) => (
                    <div key={idx} className="resultItem">
                      {row.error ? `ERROR ${row.error}` : `OK ${row.filename}: ${row.chunks_indexed} chunks (doc_id=${row.doc_id || '-'})`}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
