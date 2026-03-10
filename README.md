# Advanced Multimodal RAG Chatbot (LangChain + React + Docker)

## Overview

- Backend: FastAPI + LangChain orchestration
- Frontend: React + nginx reverse proxy
- Vector DB: Qdrant (local Docker volume)
- Embeddings:
  - Text: OpenAI embeddings
  - Image: CLIP (`clip-ViT-B-32`)
- Optional reranker: Cohere
- Authentication: JWT-based user authentication
- Database: SQLite for user and file management

## New Features

### User Authentication
- Register/Login system with JWT tokens
- Secure password hashing with bcrypt
- Token-based API authentication

### User-Specific File Management
- Each user has isolated file storage
- Files are stored in user-specific directories
- Database tracking of all uploaded files
- View all your uploaded files with metadata
- Delete files and their associated vectors

## Current UX Flows

1. **Login/Register**
- First-time users register with username and password
- Existing users login to access their files
- JWT token stored in browser localStorage

2. **Upload Files**
- Navigate to "Upload Files" from sidebar
- Select and upload files to your personal index
- Files are automatically indexed with user-specific metadata

3. **My Files**
- View all your uploaded files
- See file metadata (type, chunks, upload date)
- Delete files and their vectors permanently

4. **Chat**
- Ask questions against your indexed knowledge
- Optional file upload is ad-hoc for that message
- Ad-hoc chat file is not permanently indexed
- Only searches your own files (user isolation)

## UI Preview

![Chat Screen](docs/images/chat-screen.png)

## Supported File Types

- Documents: `.txt`, `.md`, `.pdf`, `.doc`, `.docx`, `.csv`
- Images: `.png`, `.jpg`, `.jpeg`, `.webp`

## Metadata Stored During Indexing

- `doc_id` (auto-generated UUID)
- `chunk_id`
- `uploaded_at` (UTC ISO timestamp)
- `file_type`
- `content_hash` (SHA-256 of raw file bytes)
- `tags` (auto-generated heuristic tags)
- `owner_id` (user ID - automatically set)
- `tenant_id` (currently stored as `null`)
- `page_no` (placeholder)

## API Endpoints

### Authentication
- `POST /register` - Register new user
- `POST /login` - Login and get JWT token

### Files
- `POST /upload` - Upload and index file (requires auth)
- `GET /files` - List user's files (requires auth)
- `DELETE /files/{file_id}` - Delete file and vectors (requires auth)

### Chat
- `GET /health` - Health check
- `POST /ask` - Ask question (requires auth, filters by user)
- `POST /ask-with-file` - Ask with ad-hoc file (requires auth)
- `POST /chat` - Chat endpoint (requires auth, filters by user)

### Authentication Header
All authenticated endpoints require:
```
Authorization: Bearer <jwt_token>
```

### Filters

Filtering is automatically applied by user:
- `owner_id` (automatically set to current user)
- `tenant_id`
- `file_type`
- `tags`

## Database Schema

### Users Table
- `id` - Primary key
- `username` - Unique username
- `password_hash` - Bcrypt hashed password
- `created_at` - Registration timestamp

### Files Table
- `id` - Primary key
- `user_id` - Foreign key to users
- `doc_id` - Unique document ID (for vector deletion)
- `filename` - Original filename
- `file_path` - Physical file path
- `file_type` - File extension
- `chunks_indexed` - Number of chunks created
- `uploaded_at` - Upload timestamp

## Startup Behavior

- Backend initializes database on startup
- Backend performs warmup by initializing `RagService`
- During warmup, `/chat` requests can fail with `502` from frontend proxy
- Wait for backend logs showing startup completion before sending first request

## Run

```bash
docker compose up -d --build --force-recreate backend frontend
```

Open:
- Frontend: `http://localhost:8502`
- Backend docs: `http://localhost:8001/docs`

## Persistence

- Qdrant data: `backend/data/qdrant`
- Uploaded files: `backend/data/uploads/{user_id}/`
- SQLite database: `backend/data/app.db`

## Environment Variables

Add to `.env`:
```
JWT_SECRET_KEY=your-secret-key-here
```

## Security Notes

- Change `JWT_SECRET_KEY` in production
- Passwords are hashed with bcrypt
- JWT tokens expire after 24 hours
- User files are isolated by user_id
- Vector store filters ensure users only access their own data

## Notes

- Frontend calls backend via nginx path `/api`
- Ensure valid provider keys are set in `.env`
- Each user's files are stored in separate directories
- Deleting a file removes: database record, physical file, and all vectors
