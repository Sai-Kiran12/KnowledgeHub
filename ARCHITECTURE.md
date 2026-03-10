# System Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Browser                             │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  React Frontend (Port 8502)                            │    │
│  │  - Login/Register Page                                 │    │
│  │  - Chat Interface                                      │    │
│  │  - File Upload Page                                    │    │
│  │  - File Management Page                                │    │
│  │  - JWT Token Storage (localStorage)                    │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP + JWT Token
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Nginx Reverse Proxy                         │
│                    /api → backend:8000                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FastAPI Backend (Port 8001)                    │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Authentication Layer                                   │    │
│  │  - JWT Token Validation                                │    │
│  │  - User Extraction                                     │    │
│  │  - Password Hashing (bcrypt)                           │    │
│  └────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  API Endpoints                                          │    │
│  │  - /register, /login                                   │    │
│  │  - /upload, /files, /files/{id}                        │    │
│  │  - /chat, /ask, /ask-with-file                         │    │
│  └────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  RAG Service                                            │    │
│  │  - Document Loading                                    │    │
│  │  - Text Chunking                                       │    │
│  │  - Embedding Generation                                │    │
│  │  - Query Expansion                                     │    │
│  │  - Retrieval & Reranking                               │    │
│  │  - Answer Generation                                   │    │
│  │  - Vector Deletion                                     │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐
│  SQLite Database │  │   Qdrant     │  │  File Storage    │
│                  │  │  Vector DB   │  │                  │
│  ┌────────────┐  │  │              │  │  data/uploads/   │
│  │   users    │  │  │  Text Coll.  │  │    ├─ user_1/   │
│  │   files    │  │  │  Image Coll. │  │    ├─ user_2/   │
│  └────────────┘  │  │              │  │    └─ user_N/   │
│                  │  │  Port 6333   │  │                  │
│  data/app.db     │  │              │  │                  │
└──────────────────┘  └──────────────┘  └──────────────────┘
```

## Authentication Flow

```
┌──────────┐                                    ┌──────────┐
│  Client  │                                    │  Backend │
└────┬─────┘                                    └────┬─────┘
     │                                                │
     │  POST /register                                │
     │  {username, password}                          │
     ├───────────────────────────────────────────────>│
     │                                                │
     │                                    Hash password (bcrypt)
     │                                    Create user in DB
     │                                    Generate JWT token
     │                                                │
     │  {access_token, user_id, username}             │
     │<───────────────────────────────────────────────┤
     │                                                │
     │  Store token in localStorage                   │
     │                                                │
     │  POST /upload                                  │
     │  Authorization: Bearer <token>                 │
     ├───────────────────────────────────────────────>│
     │                                                │
     │                                    Validate JWT
     │                                    Extract user_id
     │                                    Process upload
     │                                                │
     │  {filename, chunks_indexed, doc_id}            │
     │<───────────────────────────────────────────────┤
     │                                                │
```

## File Upload Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Client  │     │  Backend │     │ Database │     │  Qdrant  │     │   Disk   │
└────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                 │                │                │
     │  Upload File   │                 │                │                │
     ├───────────────>│                 │                │                │
     │                │                 │                │                │
     │           Validate Auth          │                │                │
     │           Extract user_id        │                │                │
     │                │                 │                │                │
     │           Generate doc_id        │                │                │
     │                │                 │                │                │
     │                │                 │                │   Save File    │
     │                │                 │                │───────────────>│
     │                │                 │                │                │
     │           Chunk & Embed          │                │                │
     │                │                 │                │                │
     │                │                 │   Store Vectors│                │
     │                │                 │───────────────>│                │
     │                │                 │                │                │
     │                │   Create Record │                │                │
     │                │────────────────>│                │                │
     │                │                 │                │                │
     │  Response      │                 │                │                │
     │<───────────────┤                 │                │                │
     │                │                 │                │                │
```

## File Deletion Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Client  │     │  Backend │     │ Database │     │  Qdrant  │     │   Disk   │
└────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                 │                │                │
     │ DELETE /files/1│                 │                │                │
     ├───────────────>│                 │                │                │
     │                │                 │                │                │
     │           Validate Auth          │                │                │
     │           Extract user_id        │                │                │
     │                │                 │                │                │
     │                │   Get File Info │                │                │
     │                │────────────────>│                │                │
     │                │   (verify owner)│                │                │
     │                │<────────────────┤                │                │
     │                │                 │                │                │
     │                │                 │  Delete Vectors│                │
     │                │                 │───────────────>│                │
     │                │                 │  (by doc_id)   │                │
     │                │                 │                │                │
     │                │                 │                │  Delete File   │
     │                │                 │                │───────────────>│
     │                │                 │                │                │
     │                │  Delete Record  │                │                │
     │                │────────────────>│                │                │
     │                │                 │                │                │
     │  Success       │                 │                │                │
     │<───────────────┤                 │                │                │
     │                │                 │                │                │
```

## Chat/Query Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Client  │     │  Backend │     │  Qdrant  │     │  OpenAI  │     │  Cohere  │
└────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                 │                │                │
     │  POST /chat    │                 │                │                │
     │  {question}    │                 │                │                │
     ├───────────────>│                 │                │                │
     │                │                 │                │                │
     │           Validate Auth          │                │                │
     │           Extract user_id        │                │                │
     │                │                 │                │                │
     │           Expand Query           │                │                │
     │                │                 │   Generate     │                │
     │                │                 │   Variations   │                │
     │                │                 │───────────────>│                │
     │                │                 │<───────────────┤                │
     │                │                 │                │                │
     │           Embed Queries          │                │                │
     │                │                 │   Embed        │                │
     │                │                 │───────────────>│                │
     │                │                 │<───────────────┤                │
     │                │                 │                │                │
     │           Retrieve (filter by user_id)           │                │
     │                │   Search        │                │                │
     │                │────────────────>│                │                │
     │                │<────────────────┤                │                │
     │                │                 │                │                │
     │           Rerank Results         │                │                │
     │                │                 │                │   Rerank       │
     │                │                 │                │───────────────>│
     │                │                 │                │<───────────────┤
     │                │                 │                │                │
     │           Generate Answer        │                │                │
     │                │                 │   Generate     │                │
     │                │                 │───────────────>│                │
     │                │                 │<───────────────┤                │
     │                │                 │                │                │
     │  Response      │                 │                │                │
     │<───────────────┤                 │                │                │
     │                │                 │                │                │
```

## Data Isolation

```
User 1                          User 2                          User 3
  │                               │                               │
  ├─ data/uploads/1/              ├─ data/uploads/2/              ├─ data/uploads/3/
  │    ├─ doc1_file.pdf           │    ├─ doc5_file.txt           │    ├─ doc9_file.md
  │    └─ doc2_image.png          │    └─ doc6_image.jpg          │    └─ doc10_file.pdf
  │                               │                               │
  ├─ Database Records             ├─ Database Records             ├─ Database Records
  │    ├─ file_id: 1              │    ├─ file_id: 3              │    ├─ file_id: 5
  │    │   user_id: 1             │    │   user_id: 2             │    │   user_id: 3
  │    │   doc_id: doc1           │    │   doc_id: doc5           │    │   doc_id: doc9
  │    └─ file_id: 2              │    └─ file_id: 4              │    └─ file_id: 6
  │        user_id: 1             │        user_id: 2             │        user_id: 3
  │        doc_id: doc2           │        doc_id: doc6           │        doc_id: doc10
  │                               │                               │
  └─ Qdrant Vectors               └─ Qdrant Vectors               └─ Qdrant Vectors
       (owner_id: "1")                 (owner_id: "2")                 (owner_id: "3")
       ├─ doc1:chunk0                  ├─ doc5:chunk0                  ├─ doc9:chunk0
       ├─ doc1:chunk1                  ├─ doc5:chunk1                  ├─ doc9:chunk1
       ├─ doc2:image                   └─ doc6:image                   └─ doc10:chunk0

       ↑ Filtered by owner_id          ↑ Filtered by owner_id          ↑ Filtered by owner_id
       User 1 can ONLY access          User 2 can ONLY access          User 3 can ONLY access
       their own vectors               their own vectors               their own vectors
```

## Security Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: Frontend Authentication                                │
│  - Token stored in localStorage                                  │
│  - Redirect to login if no token                                 │
│  - Include token in all API requests                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: API Authentication                                     │
│  - JWT token validation                                          │
│  - Token expiration check                                        │
│  - User extraction from token                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: Authorization                                          │
│  - Verify user owns requested resource                           │
│  - Check file ownership before deletion                          │
│  - Automatic user_id filtering                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 4: Data Isolation                                         │
│  - Files stored in user-specific directories                     │
│  - Database foreign keys enforce relationships                   │
│  - Vector store filtered by owner_id                             │
└─────────────────────────────────────────────────────────────────┘
```
