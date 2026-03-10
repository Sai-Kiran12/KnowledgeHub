# Migration Guide: Adding Authentication & File Management

## Summary of Changes

This restructuring adds:
1. **User Authentication** - JWT-based login/register system
2. **User-Specific File Storage** - Each user has isolated files
3. **File Management UI** - View and delete uploaded files
4. **Database Tracking** - SQLite database for users and files

## Backend Changes

### New Files
- `backend/app/database.py` - SQLite database operations
- `backend/app/auth.py` - JWT authentication utilities

### Modified Files
- `backend/app/main.py` - Added auth endpoints and user filtering
- `backend/app/schemas.py` - Added auth and file management schemas
- `backend/app/config.py` - Added JWT secret configuration
- `backend/app/services/rag_service.py` - Added delete_by_doc_id method
- `backend/requirements.txt` - Added passlib and PyJWT

### New Dependencies
```
passlib[bcrypt]==1.7.4
PyJWT==2.10.1
```

## Frontend Changes

### Modified Files
- `frontend/src/App.jsx` - Complete rewrite with:
  - Login/Register page
  - File management page
  - JWT token handling
  - User-specific API calls

- `frontend/src/styles.css` - Added styles for:
  - Login page
  - File management page
  - User info display

## Database Structure

### Automatic Initialization
The database is automatically created on first startup with two tables:

**users**
- id (PRIMARY KEY)
- username (UNIQUE)
- password_hash
- created_at

**files**
- id (PRIMARY KEY)
- user_id (FOREIGN KEY)
- doc_id (UNIQUE)
- filename
- file_path
- file_type
- chunks_indexed
- uploaded_at

## Migration Steps

### 1. Update Backend Dependencies
```bash
cd backend
pip install passlib[bcrypt]==1.7.4 PyJWT==2.10.1
```

### 2. Set JWT Secret (Optional but Recommended)
Add to `.env`:
```
JWT_SECRET_KEY=your-production-secret-key-here
```

### 3. Rebuild Docker Containers
```bash
docker compose down
docker compose up -d --build --force-recreate backend frontend
```

### 4. Database Auto-Creation
The SQLite database will be automatically created at:
```
backend/data/app.db
```

### 5. First User Registration
- Open `http://localhost:8502`
- Click "Don't have an account? Register"
- Create your first user account

## Breaking Changes

### API Changes
All endpoints except `/health`, `/register`, and `/login` now require authentication:
- Add `Authorization: Bearer <token>` header
- Token obtained from `/login` or `/register`

### File Storage
- Old files in `backend/data/uploads/` won't be accessible
- New files stored in `backend/data/uploads/{user_id}/`
- Each user only sees their own files

### Metadata Changes
- `owner_id` now automatically set to user ID (was null)
- Files tracked in database with doc_id for deletion

## Migrating Existing Files (Optional)

If you have existing files you want to migrate to a user:

1. Register a user and note their user_id from database
2. Move files to `backend/data/uploads/{user_id}/`
3. Manually insert records into files table
4. Ensure vectors in Qdrant have matching owner_id

## Testing the Migration

1. **Register a new user**
   ```bash
   curl -X POST http://localhost:8001/register \
     -H "Content-Type: application/json" \
     -d '{"username":"testuser","password":"testpass123"}'
   ```

2. **Login**
   ```bash
   curl -X POST http://localhost:8001/login \
     -H "Content-Type: application/json" \
     -d '{"username":"testuser","password":"testpass123"}'
   ```

3. **Upload a file**
   ```bash
   curl -X POST http://localhost:8001/upload \
     -H "Authorization: Bearer <your_token>" \
     -F "file=@test.txt"
   ```

4. **List files**
   ```bash
   curl http://localhost:8001/files \
     -H "Authorization: Bearer <your_token>"
   ```

5. **Delete a file**
   ```bash
   curl -X DELETE http://localhost:8001/files/1 \
     -H "Authorization: Bearer <your_token>"
   ```

## Rollback Plan

If you need to rollback:

1. Restore old versions of modified files
2. Remove new files (database.py, auth.py)
3. Restore old requirements.txt
4. Rebuild containers

## Security Considerations

- **Change JWT_SECRET_KEY in production**
- Passwords are hashed with bcrypt (secure)
- Tokens expire after 24 hours
- User isolation enforced at API and storage level
- Consider adding rate limiting for production
- Consider HTTPS for production deployment

## Performance Impact

- Minimal overhead from JWT validation
- SQLite queries are fast for file listing
- User filtering in Qdrant is efficient
- No impact on RAG performance

## Future Enhancements

Possible additions:
- Email verification
- Password reset functionality
- User roles and permissions
- Team/tenant support
- File sharing between users
- Usage quotas per user
- Audit logging
