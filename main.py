from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import oracledb
import hashlib
import os
from datetime import datetime
import traceback
import requests

# Initialize FastAPI
app = FastAPI(title="LawChain AI API")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Groq AI Configuration (FREE!)
GROQ_API_KEY=""
GROQ_API_URL = ""

# Oracle DB Configuration
DB_CONFIG = {
    "user": "lawchain_user",
    "password": "your_password",
    "dsn": "localhost:1521/XEPDB1"
}

# Test connection
try:
    conn = oracledb.connect(**DB_CONFIG)
    print("✓ Connected to Oracle XE PDB!")
    conn.close()
except Exception as e:
    print(f"✗ Database connection failed: {e}")


# Pydantic Models
class CaseCreate(BaseModel):
    case_title: str
    client_name: str
    client_email: str
    client_address: str
    lawyer_name: str
    lawyer_email: str
    case_type: str
    description: str
    client_wallet: str
    lawyer_wallet: str

class CaseUpdate(BaseModel):
    case_title: str
    client_name: str
    client_email: str
    client_address: str
    lawyer_name: str
    lawyer_email: str
    case_type: str
    description: str

class ChatRequest(BaseModel):
    message: str
    case_id: Optional[int] = None
    context: Optional[str] = None

class DocumentVerify(BaseModel):
    document_hash: str

class HearingCreate(BaseModel):
    case_id: int
    hearing_date: str
    hearing_time: str
    court_name: str
    notes: str

class StatusUpdate(BaseModel):
    status: str

class NoticeRequest(BaseModel):
    case_type: str
    party_from: str
    party_to: str
    issue: str

class SummarizeRequest(BaseModel):
    case_id: int
    document_text: str


# Database Helper Functions
def get_db_connection():
    try:
        connection = oracledb.connect(**DB_CONFIG)
        return connection
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

def init_database():
    """Initialize database tables - Oracle compatible"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Create Cases Table
        cursor.execute("SELECT table_name FROM user_tables WHERE table_name='CASES'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE cases (
                    case_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    case_title VARCHAR2(500),
                    client_name VARCHAR2(200),
                    client_email VARCHAR2(200),
                    client_address VARCHAR2(500),
                    lawyer_name VARCHAR2(200),
                    lawyer_email VARCHAR2(200),
                    case_type VARCHAR2(100),
                    description CLOB,
                    client_wallet VARCHAR2(100),
                    lawyer_wallet VARCHAR2(100),
                    blockchain_tx VARCHAR2(200),
                    status VARCHAR2(50) DEFAULT 'Active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("✓ Cases table created")
        else:
            print("✓ Cases table already exists")
        
        # Create Documents Table
        cursor.execute("SELECT table_name FROM user_tables WHERE table_name='DOCUMENTS'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE documents (
                    doc_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    case_id NUMBER,
                    document_name VARCHAR2(300),
                    document_hash VARCHAR2(200) UNIQUE,
                    document_type VARCHAR2(100),
                    uploaded_by VARCHAR2(200),
                    blockchain_tx VARCHAR2(200),
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT fk_case_docs FOREIGN KEY (case_id) REFERENCES cases(case_id)
                )
            """)
            print("✓ Documents table created")
        else:
            print("✓ Documents table already exists")
        
        # Create Hearings Table
        cursor.execute("SELECT table_name FROM user_tables WHERE table_name='HEARINGS'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE hearings (
                    hearing_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    case_id NUMBER,
                    hearing_date DATE,
                    hearing_time VARCHAR2(20),
                    court_name VARCHAR2(300),
                    notes CLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT fk_case_hearings FOREIGN KEY (case_id) REFERENCES cases(case_id)
                )
            """)
            print("✓ Hearings table created")
        else:
            print("✓ Hearings table already exists")
        
        conn.commit()
        print("✓ Database initialization complete")
        
    except Exception as e:
        print(f"✗ Error during table creation: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


# AI Helper Function using Groq
def chat_with_groq(prompt: str) -> str:
    """Chat with Groq AI - FREE and FAST"""
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",  # Free, fast, and powerful
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        response = requests.post(GROQ_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        return data['choices'][0]['message']['content']
    
    except Exception as e:
        print(f"Groq AI Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")


# ==================== API ENDPOINTS ====================

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    try:
        init_database()
    except Exception as e:
        print(f"Database initialization warning: {e}")

@app.get("/")
async def root():
    return {
        "message": "LawChain AI API with Groq", 
        "status": "running",
        "version": "2.0"
    }


# ==================== CASE MANAGEMENT ====================

@app.post("/api/cases")
async def create_case(case: CaseCreate):
    """Create a new legal case"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        case_id_var = cursor.var(oracledb.NUMBER)
        
        cursor.execute("""
            INSERT INTO cases (case_title, client_name, client_email, client_address, 
                             lawyer_name, lawyer_email, case_type, description, 
                             client_wallet, lawyer_wallet)
            VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10)
            RETURNING case_id INTO :11
        """, [
            case.case_title, case.client_name, case.client_email, case.client_address,
            case.lawyer_name, case.lawyer_email, case.case_type, case.description,
            case.client_wallet, case.lawyer_wallet, case_id_var
        ])
        
        case_id = case_id_var.getvalue()[0]
        conn.commit()
        
        return {
            "success": True,
            "case_id": int(case_id),
            "message": "Case created successfully"
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error creating case: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.get("/api/cases")
async def get_all_cases():
    """Get all cases"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT case_id, case_title, client_name, lawyer_name, 
                   case_type, status, created_at
            FROM cases
            ORDER BY created_at DESC
        """)
        
        cases = []
        for row in cursor:
            cases.append({
                "case_id": row[0],
                "case_title": row[1],
                "client_name": row[2],
                "lawyer_name": row[3],
                "case_type": row[4],
                "status": row[5],
                "created_at": row[6].isoformat() if row[6] else None
            })
        
        return {"cases": cases}
        
    except Exception as e:
        print(f"Error fetching cases: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.get("/api/cases/{case_id}")
async def get_case(case_id: int):
    """Get specific case details"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM cases WHERE case_id = :1", [case_id])
        
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Case not found")
        
        case_data = {
            "case_id": row[0],
            "case_title": row[1],
            "client_name": row[2],
            "client_email": row[3],
            "client_address": row[4],
            "lawyer_name": row[5],
            "lawyer_email": row[6],
            "case_type": row[7],
            "description": row[8],
            "client_wallet": row[9],
            "lawyer_wallet": row[10],
            "blockchain_tx": row[11],
            "status": row[12],
            "created_at": row[13].isoformat() if row[13] else None
        }
        
        return case_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.put("/api/cases/{case_id}")
async def update_case(case_id: int, case: CaseUpdate):
    """Update entire case details"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE cases 
            SET case_title = :1, client_name = :2, client_email = :3,
                client_address = :4, lawyer_name = :5, lawyer_email = :6,
                case_type = :7, description = :8
            WHERE case_id = :9
        """, [
            case.case_title, case.client_name, case.client_email,
            case.client_address, case.lawyer_name, case.lawyer_email,
            case.case_type, case.description, case_id
        ])
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Case updated successfully"
        }
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.put("/api/cases/{case_id}/status")
async def update_case_status(case_id: int, status_data: StatusUpdate):
    """Update case status"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE cases 
            SET status = :1
            WHERE case_id = :2
        """, [status_data.status, case_id])
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Status updated successfully"
        }
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.delete("/api/cases/{case_id}")
async def delete_case(case_id: int):
    """Delete case and all related data"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete related records first (foreign key constraints)
        cursor.execute("DELETE FROM hearings WHERE case_id = :1", [case_id])
        cursor.execute("DELETE FROM documents WHERE case_id = :1", [case_id])
        cursor.execute("DELETE FROM cases WHERE case_id = :1", [case_id])
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Case deleted successfully"
        }
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.get("/api/cases/search/{query}")
async def search_cases(query: str):
    """Search cases by title, client, lawyer, or type"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        search_query = f"%{query}%"
        cursor.execute("""
            SELECT case_id, case_title, client_name, lawyer_name, 
                   case_type, status, created_at
            FROM cases
            WHERE UPPER(case_title) LIKE UPPER(:1)
               OR UPPER(client_name) LIKE UPPER(:1)
               OR UPPER(lawyer_name) LIKE UPPER(:1)
               OR UPPER(case_type) LIKE UPPER(:1)
            ORDER BY created_at DESC
        """, [search_query])
        
        cases = []
        for row in cursor:
            cases.append({
                "case_id": row[0],
                "case_title": row[1],
                "client_name": row[2],
                "lawyer_name": row[3],
                "case_type": row[4],
                "status": row[5],
                "created_at": row[6].isoformat() if row[6] else None
            })
        
        return {"cases": cases}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.get("/api/cases/stats/overview")
async def get_case_stats():
    """Get case statistics overview"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END) as closed,
                SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending
            FROM cases
        """)
        
        row = cursor.fetchone()
        
        return {
            "total": row[0] or 0,
            "active": row[1] or 0,
            "closed": row[2] or 0,
            "pending": row[3] or 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ==================== DOCUMENT MANAGEMENT ====================

@app.post("/api/documents/upload")
async def upload_document(
    case_id: int,
    document_name: str,
    document_type: str,
    uploaded_by: str,
    file: UploadFile = File(...)
):
    """Upload and hash a document"""
    conn = None
    cursor = None
    try:
        # Read file and compute hash
        content = await file.read()
        document_hash = hashlib.sha256(content).hexdigest()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO documents (case_id, document_name, document_hash, 
                                 document_type, uploaded_by)
            VALUES (:1, :2, :3, :4, :5)
        """, [case_id, document_name, document_hash, document_type, uploaded_by])
        
        conn.commit()
        
        return {
            "success": True,
            "document_hash": document_hash,
            "message": "Document uploaded successfully"
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error uploading document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.get("/api/documents/{case_id}")
async def get_documents(case_id: int):
    """Get all documents for a case"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT doc_id, document_name, document_hash, document_type, 
                   uploaded_by, uploaded_at
            FROM documents
            WHERE case_id = :1
            ORDER BY uploaded_at DESC
        """, [case_id])
        
        documents = []
        for row in cursor:
            documents.append({
                "doc_id": row[0],
                "document_name": row[1],
                "document_hash": row[2],
                "document_type": row[3],
                "uploaded_by": row[4],
                "uploaded_at": row[5].isoformat() if row[5] else None
            })
        
        return {"documents": documents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.post("/api/documents/verify")
async def verify_document(doc: DocumentVerify):
    """Verify document hash exists in blockchain"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT document_name, uploaded_by, uploaded_at 
            FROM documents 
            WHERE document_hash = :1
        """, [doc.document_hash])
        
        row = cursor.fetchone()
        
        if row:
            return {
                "verified": True,
                "document_name": row[0],
                "uploaded_by": row[1],
                "uploaded_at": row[2].isoformat() if row[2] else None
            }
        else:
            return {
                "verified": False, 
                "message": "Document not found in blockchain"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ==================== HEARINGS MANAGEMENT ====================

@app.post("/api/hearings")
async def create_hearing(hearing: HearingCreate):
    """Add a new hearing to a case"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO hearings (case_id, hearing_date, hearing_time, court_name, notes)
            VALUES (:1, TO_DATE(:2, 'YYYY-MM-DD'), :3, :4, :5)
        """, [hearing.case_id, hearing.hearing_date, hearing.hearing_time, 
              hearing.court_name, hearing.notes])
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Hearing added successfully"
        }
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error creating hearing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.get("/api/hearings/{case_id}")
async def get_hearings(case_id: int):
    """Get all hearings for a case"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT hearing_id, hearing_date, hearing_time, court_name, notes, created_at
            FROM hearings
            WHERE case_id = :1
            ORDER BY hearing_date DESC
        """, [case_id])
        
        hearings = []
        for row in cursor:
            hearings.append({
                "hearing_id": row[0],
                "hearing_date": row[1].isoformat() if row[1] else None,
                "hearing_time": row[2],
                "court_name": row[3],
                "notes": row[4],
                "created_at": row[5].isoformat() if row[5] else None
            })
        
        return {"hearings": hearings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ==================== AI CHAT ENDPOINTS ====================

@app.post("/api/chat")
async def chat_with_ai(request: ChatRequest):
    """Chat with Groq AI for legal assistance"""
    conn = None
    cursor = None
    try:
        context = ""
        if request.case_id:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT case_title, case_type, description 
                FROM cases WHERE case_id = :1
            """, [request.case_id])
            
            row = cursor.fetchone()
            if row:
                context = f"Case Context - Title: {row[0]}, Type: {row[1]}, Description: {row[2]}"
        
        system_prompt = """You are a legal AI assistant for LawChain AI. 
        You help with:
        1. Legal document summaries
        2. Legal notice generation
        3. Case analysis and insights
        4. Legal questions and guidance
        
        Maintain professional tone and cite relevant laws when applicable."""
        
        full_prompt = f"{system_prompt}\n\n"
        if context:
            full_prompt += f"Context: {context}\n\n"
        if request.context:
            full_prompt += f"Additional Context: {request.context}\n\n"
        full_prompt += f"User Query: {request.message}"
        
        response_text = chat_with_groq(full_prompt)
        
        return {
            "response": response_text,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"Error in chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.post("/api/chat/summarize")
async def summarize_document(request: SummarizeRequest):
    """Summarize legal document using AI"""
    try:
        prompt = f"""Summarize this legal document clearly and concisely. 
        Highlight key points, parties involved, and important clauses:
        
        {request.document_text}"""
        
        response_text = chat_with_groq(prompt)
        
        return {
            "summary": response_text, 
            "case_id": request.case_id
        }
    except Exception as e:
        print(f"Error summarizing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/generate-notice")
async def generate_legal_notice(request: NoticeRequest):
    """Generate legal notice template using AI"""
    try:
        prompt = f"""Generate a professional legal notice template for:
        Case Type: {request.case_type}
        From: {request.party_from}
        To: {request.party_to}
        Issue: {request.issue}
        
        Include proper legal formatting, professional language, and relevant legal clauses."""
        
        response_text = chat_with_groq(prompt)
        
        return {"notice": response_text}
    except Exception as e:
        print(f"Error generating notice: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== HEALTH CHECK ====================

@app.get("/health")
async def health_check():
    """Check system health"""
    try:
        conn = get_db_connection()
        conn.close()
        db_status = "connected"
    except:
        db_status = "disconnected"
    
    return {
        "status": "running",
        "database": db_status,
        "ai_provider": "Groq (Llama 3.3 70B)",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# from fastapi import FastAPI, HTTPException, UploadFile, File
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import Optional, List
# import google.generativeai as genai
# import oracledb
# import hashlib
# import os
# from datetime import datetime
# import json

# # Initialize FastAPI
# app = FastAPI(title="LawChain AI API")

# # CORS Configuration
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # Gemini AI Configuration
# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "your_gemini_api_key_here")
# genai.configure(api_key=GEMINI_API_KEY)
# model = genai.GenerativeModel('gemini-pro')

# # Oracle DB Configuration
# DB_CONFIG = {
#     "user": "lawchain_user",
#     "password": "your_password",
#     "dsn": "localhost:1521/XEPDB1"
# }

# conn = oracledb.connect(**DB_CONFIG)
# print("Connected to Oracle XE PDB!")
# conn.close()


# # Pydantic Models
# class CaseCreate(BaseModel):
#     case_title: str
#     client_name: str
#     client_email: str
#     client_address: str
#     lawyer_name: str
#     lawyer_email: str
#     case_type: str
#     description: str
#     client_wallet: str
#     lawyer_wallet: str

# class ChatRequest(BaseModel):
#     message: str
#     case_id: Optional[int] = None
#     context: Optional[str] = None

# class DocumentVerify(BaseModel):
#     document_hash: str

# # Database Helper Functions
# def get_db_connection():
#     try:
#         connection = oracledb.connect(**DB_CONFIG)
#         return connection
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

# def init_database():
#     """Initialize database tables - Oracle compatible"""
#     conn = get_db_connection()
#     cursor = conn.cursor()

#     try:
#         # Create Cases Table
#         cursor.execute("SELECT table_name FROM user_tables WHERE table_name='CASES'")
#         if not cursor.fetchone():
#             cursor.execute("""
#                 CREATE TABLE cases (
#                     case_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
#                     case_title VARCHAR2(500),
#                     client_name VARCHAR2(200),
#                     client_email VARCHAR2(200),
#                     client_address VARCHAR2(500),
#                     lawyer_name VARCHAR2(200),
#                     lawyer_email VARCHAR2(200),
#                     case_type VARCHAR2(100),
#                     description CLOB,
#                     client_wallet VARCHAR2(100),
#                     lawyer_wallet VARCHAR2(100),
#                     blockchain_tx VARCHAR2(200),
#                     status VARCHAR2(50) DEFAULT 'Active',
#                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#                 )
#             """)
#             print("✓ Cases table created")
#         else:
#             print("✓ Cases table already exists")
        
#         # Create Documents Table
#         cursor.execute("SELECT table_name FROM user_tables WHERE table_name='DOCUMENTS'")
#         if not cursor.fetchone():
#             cursor.execute("""
#                 CREATE TABLE documents (
#                     doc_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
#                     case_id NUMBER,
#                     document_name VARCHAR2(300),
#                     document_hash VARCHAR2(200) UNIQUE,
#                     document_type VARCHAR2(100),
#                     uploaded_by VARCHAR2(200),
#                     blockchain_tx VARCHAR2(200),
#                     uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#                     CONSTRAINT fk_case_docs FOREIGN KEY (case_id) REFERENCES cases(case_id)
#                 )
#             """)
#             print("✓ Documents table created")
#         else:
#             print("✓ Documents table already exists")
        
#         # Create Hearings Table
#         cursor.execute("SELECT table_name FROM user_tables WHERE table_name='HEARINGS'")
#         if not cursor.fetchone():
#             cursor.execute("""
#                 CREATE TABLE hearings (
#                     hearing_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
#                     case_id NUMBER,
#                     hearing_date DATE,
#                     hearing_time VARCHAR2(20),
#                     court_name VARCHAR2(300),
#                     notes CLOB,
#                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#                     CONSTRAINT fk_case_hearings FOREIGN KEY (case_id) REFERENCES cases(case_id)
#                 )
#             """)
#             print("✓ Hearings table created")
#         else:
#             print("✓ Hearings table already exists")
        
#         conn.commit()
#         print("✓ Database initialization complete")
        
#     except Exception as e:
#         print(f"✗ Error during table creation: {e}")
#         conn.rollback()
#     finally:
#         cursor.close()
#         conn.close()


# @app.post("/api/cases")
# async def create_case(case: CaseCreate):
#     """Create a new legal case - Oracle compatible"""
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         # Create output variable for the case_id
#         case_id_var = cursor.var(int)
        
#         cursor.execute("""
#             INSERT INTO cases (case_title, client_name, client_email, client_address, 
#                              lawyer_name, lawyer_email, case_type, description, 
#                              client_wallet, lawyer_wallet)
#             VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10)
#             RETURNING case_id INTO :case_id
#         """, [
#             case.case_title, 
#             case.client_name, 
#             case.client_email, 
#             case.client_address,
#             case.lawyer_name, 
#             case.lawyer_email, 
#             case.case_type, 
#             case.description,
#             case.client_wallet, 
#             case.lawyer_wallet,
#             case_id_var
#         ])
        
#         # Extract the case_id from the output variable
#         case_id = case_id_var.getvalue()[0]
#         conn.commit()
        
#         cursor.close()
#         conn.close()
        
#         return {
#             "success": True,
#             "case_id": case_id,
#             "message": "Case created successfully"
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# # API Endpoints

# @app.on_event("startup")
# async def startup_event():
#     """Initialize database on startup"""
#     try:
#         init_database()
#     except Exception as e:
#         print(f"Database initialization warning: {e}")

# @app.get("/")
# async def root():
#     return {"message": "LawChain AI API", "status": "running"}

# @app.post("/api/cases")
# async def create_case(case: CaseCreate):
#     """Create a new legal case"""
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         cursor.execute("""
#             INSERT INTO cases (case_title, client_name, client_email, client_address, 
#                              lawyer_name, lawyer_email, case_type, description, 
#                              client_wallet, lawyer_wallet)
#             VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10)
#             RETURNING case_id INTO :case_id
#         """, [case.case_title, case.client_name, case.client_email, case.client_address,
#               case.lawyer_name, case.lawyer_email, case.case_type, case.description,
#               case.client_wallet, case.lawyer_wallet],
#         case_id=cursor.var(int))
        
#         case_id = cursor.getvalue(0)[0]
#         conn.commit()
        
#         cursor.close()
#         conn.close()
        
#         return {
#             "success": True,
#             "case_id": case_id,
#             "message": "Case created successfully"
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/cases")
# async def get_all_cases():
#     """Get all cases"""
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         cursor.execute("""
#             SELECT case_id, case_title, client_name, lawyer_name, 
#                    case_type, status, created_at
#             FROM cases
#             ORDER BY created_at DESC
#         """)
        
#         cases = []
#         for row in cursor:
#             cases.append({
#                 "case_id": row[0],
#                 "case_title": row[1],
#                 "client_name": row[2],
#                 "lawyer_name": row[3],
#                 "case_type": row[4],
#                 "status": row[5],
#                 "created_at": row[6].isoformat() if row[6] else None
#             })
        
#         cursor.close()
#         conn.close()
        
#         return {"cases": cases}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/cases/{case_id}")
# async def get_case(case_id: int):
#     """Get specific case details"""
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         cursor.execute("""
#             SELECT * FROM cases WHERE case_id = :1
#         """, [case_id])
        
#         row = cursor.fetchone()
#         if not row:
#             raise HTTPException(status_code=404, detail="Case not found")
        
#         case_data = {
#             "case_id": row[0],
#             "case_title": row[1],
#             "client_name": row[2],
#             "client_email": row[3],
#             "client_address": row[4],
#             "lawyer_name": row[5],
#             "lawyer_email": row[6],
#             "case_type": row[7],
#             "description": row[8],
#             "client_wallet": row[9],
#             "lawyer_wallet": row[10],
#             "blockchain_tx": row[11],
#             "status": row[12],
#             "created_at": row[13].isoformat() if row[13] else None
#         }
        
#         cursor.close()
#         conn.close()
        
#         return case_data
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/documents/upload")
# async def upload_document(
#     case_id: int,
#     document_name: str,
#     document_type: str,
#     uploaded_by: str,
#     file: UploadFile = File(...)
# ):
#     """Upload and hash a document"""
#     try:
#         # Read file and compute hash
#         content = await file.read()
#         document_hash = hashlib.sha256(content).hexdigest()
        
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         cursor.execute("""
#             INSERT INTO documents (case_id, document_name, document_hash, 
#                                  document_type, uploaded_by)
#             VALUES (:1, :2, :3, :4, :5)
#         """, [case_id, document_name, document_hash, document_type, uploaded_by])
        
#         conn.commit()
#         cursor.close()
#         conn.close()
        
#         return {
#             "success": True,
#             "document_hash": document_hash,
#             "message": "Document uploaded successfully"
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/documents/verify")
# async def verify_document(doc: DocumentVerify):
#     """Verify document exists in blockchain"""
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         cursor.execute("""
#             SELECT document_name, uploaded_by, uploaded_at 
#             FROM documents 
#             WHERE document_hash = :1
#         """, [doc.document_hash])
        
#         row = cursor.fetchone()
#         cursor.close()
#         conn.close()
        
#         if row:
#             return {
#                 "verified": True,
#                 "document_name": row[0],
#                 "uploaded_by": row[1],
#                 "uploaded_at": row[2].isoformat() if row[2] else None
#             }
#         else:
#             return {"verified": False, "message": "Document not found"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/chat")
# async def chat_with_ai(request: ChatRequest):
#     """Chat with Gemini AI for legal assistance"""
#     try:
#         # Prepare context
#         context = ""
#         if request.case_id:
#             conn = get_db_connection()
#             cursor = conn.cursor()
            
#             cursor.execute("""
#                 SELECT case_title, case_type, description 
#                 FROM cases 
#                 WHERE case_id = :1
#             """, [request.case_id])
            
#             row = cursor.fetchone()
#             if row:
#                 context = f"Case Context - Title: {row[0]}, Type: {row[1]}, Description: {row[2]}"
            
#             cursor.close()
#             conn.close()
        
#         # Build prompt
#         system_prompt = """You are a legal AI assistant integrated into LawChain AI. 
#         You help lawyers and clients by:
#         1. Summarizing legal documents and case files
#         2. Generating draft legal notices and templates
#         3. Answering general law-related questions
#         4. Providing case analysis and insights
        
#         Always maintain professional tone and cite relevant laws when applicable."""
        
#         full_prompt = f"{system_prompt}\n\n"
#         if context:
#             full_prompt += f"Context: {context}\n\n"
#         if request.context:
#             full_prompt += f"Additional Context: {request.context}\n\n"
#         full_prompt += f"User Query: {request.message}"
        
#         # Generate response
#         response = model.generate_content(full_prompt)
        
#         return {
#             "response": response.text,
#             "timestamp": datetime.now().isoformat()
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

# @app.post("/api/chat/summarize")
# async def summarize_document(case_id: int, document_text: str):
#     """Summarize legal document"""
#     try:
#         prompt = f"""Summarize the following legal document in a clear, concise manner. 
#         Highlight key points, parties involved, and important clauses:
        
#         {document_text}"""
        
#         response = model.generate_content(prompt)
        
#         return {
#             "summary": response.text,
#             "case_id": case_id
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/chat/generate-notice")
# async def generate_legal_notice(
#     case_type: str,
#     party_from: str,
#     party_to: str,
#     issue: str
# ):
#     """Generate legal notice template"""
#     try:
#         prompt = f"""Generate a professional legal notice template for:
#         Case Type: {case_type}
#         From: {party_from}
#         To: {party_to}
#         Issue: {issue}
        
#         Include proper legal formatting and language."""
        
#         response = model.generate_content(prompt)
        
#         return {
#             "notice": response.text
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)


# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import List, Optional
# import os
# import google.generativeai as genai
# from dotenv import load_dotenv

# # Load environment variables
# load_dotenv()

# # Retrieve the Google API Key
# GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# if not GOOGLE_API_KEY:
#     raise Exception("GOOGLE_API_KEY is not set in your environment variables.")

# # Configure Gemini AI
# genai.configure(api_key=GOOGLE_API_KEY)

# # Initialize FastAPI app
# app = FastAPI(title="AI Resume Builder API", version="1.0.0")

# # Enable CORS
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # In production, restrict to your frontend domain
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # Data models
# class PersonalInfo(BaseModel):
#     fullName: str
#     email: str
#     phone: str
#     location: str
#     linkedIn: Optional[str] = None
#     portfolio: Optional[str] = None

# class Experience(BaseModel):
#     company: str
#     position: str
#     startDate: str
#     endDate: Optional[str] = None
#     description: str
#     isCurrentJob: bool = False

# class Education(BaseModel):
#     institution: str
#     degree: str
#     field: str
#     graduationYear: str
#     gpa: Optional[str] = None

# class ResumeData(BaseModel):
#     personalInfo: PersonalInfo
#     experience: List[Experience]
#     education: List[Education]
#     skills: List[str]
#     targetRole: str
#     additionalInfo: Optional[str] = None

# class ResumeRequest(BaseModel):
#     data: ResumeData
#     template: str = "professional"  # professional, modern, creative

# def generate_resume_content(resume_data: ResumeData, template: str) -> str:
#     """
#     Uses Gemini AI to generate optimized resume content.
#     """
#     # Construct detailed prompt for resume generation
#     prompt = f"""
#     Create a professional resume for the following person targeting a {resume_data.targetRole} position. 
#     Use the {template} template style.
    
#     Personal Information:
#     - Name: {resume_data.personalInfo.fullName}
#     - Email: {resume_data.personalInfo.email}
#     - Phone: {resume_data.personalInfo.phone}
#     - Location: {resume_data.personalInfo.location}
#     - LinkedIn: {resume_data.personalInfo.linkedIn or 'Not provided'}
#     - Portfolio: {resume_data.personalInfo.portfolio or 'Not provided'}
    
#     Work Experience:
#     """
    
#     for exp in resume_data.experience:
#         end_date = exp.endDate if exp.endDate else "Present"
#         prompt += f"""
#         - {exp.position} at {exp.company} ({exp.startDate} - {end_date})
#           Description: {exp.description}
#         """
    
#     prompt += f"""
    
#     Education:
#     """
#     for edu in resume_data.education:
#         prompt += f"""
#         - {edu.degree} in {edu.field} from {edu.institution} ({edu.graduationYear})
#           {f"GPA: {edu.gpa}" if edu.gpa else ""}
#         """
    
#     prompt += f"""
    
#     Skills: {', '.join(resume_data.skills)}
    
#     Additional Information: {resume_data.additionalInfo or 'None'}
    
#     Please create:
#     1. A compelling professional summary (2-3 sentences)
#     2. Optimized work experience descriptions with action verbs and quantifiable achievements
#     3. Improved skills section organized by category
#     4. Professional formatting suggestions
#     5. ATS-friendly keywords for the target role
    
#     Format the response as a structured resume with clear sections.
#     """
    
#     model = genai.GenerativeModel('gemini-1.5-flash')
#     response = model.generate_content([prompt])
#     return response.text.strip()

# def improve_resume_section(section_content: str, section_type: str, target_role: str) -> str:
#     """
#     Uses Gemini AI to improve specific resume sections.
#     """
#     prompt = f"""
#     Improve this {section_type} section for a {target_role} position.
#     Make it more professional, impactful, and ATS-friendly.
#     Use action verbs and quantify achievements where possible.
    
#     Current {section_type}:
#     {section_content}
    
#     Provide an improved version:
#     """
    
#     model = genai.GenerativeModel('gemini-1.5-flash')
#     response = model.generate_content([prompt])
#     return response.text.strip()

# @app.post("/generate-resume")
# def generate_resume(request: ResumeRequest):
#     """
#     Endpoint to generate a complete AI-optimized resume.
#     """
#     try:
#         resume_content = generate_resume_content(request.data, request.template)
#         return {
#             "success": True,
#             "resume": resume_content,
#             "template": request.template
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error generating resume: {str(e)}")

# @app.post("/improve-section")
# def improve_section(section_content: str, section_type: str, target_role: str):
#     """
#     Endpoint to improve specific resume sections.
#     """
#     try:
#         improved_content = improve_resume_section(section_content, section_type, target_role)
#         return {
#             "success": True,
#             "improved_content": improved_content
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error improving section: {str(e)}")

# @app.post("/generate-cover-letter")
# def generate_cover_letter(resume_data: ResumeData, company_name: str, job_description: str):
#     """
#     Endpoint to generate a personalized cover letter.
#     """
#     prompt = f"""
#     Create a professional cover letter for {resume_data.personalInfo.fullName} applying for a {resume_data.targetRole} 
#     position at {company_name}.
    
#     Job Description: {job_description}
    
#     Candidate Background:
#     - Skills: {', '.join(resume_data.skills)}
#     - Recent Experience: {resume_data.experience[0].position if resume_data.experience else 'Not specified'}
#     - Education: {resume_data.education[0].degree if resume_data.education else 'Not specified'}
    
#     Create a compelling, personalized cover letter that:
#     1. Shows enthusiasm for the role and company
#     2. Highlights relevant skills and experience
#     3. Demonstrates knowledge of the company/role
#     4. Maintains a professional yet engaging tone
#     5. Includes a strong opening and closing
#     """
    
#     try:
#         model = genai.GenerativeModel('gemini-1.5-flash')
#         response = model.generate_content([prompt])
#         return {
#             "success": True,
#             "cover_letter": response.text.strip()
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error generating cover letter: {str(e)}")

# @app.get("/resume-tips/{target_role}")
# def get_resume_tips(target_role: str):
#     """
#     Get AI-generated tips for specific roles.
#     """
#     prompt = f"""
#     Provide 5-7 specific resume tips for someone applying for {target_role} positions.
#     Include advice about:
#     - Key skills to highlight
#     - Important keywords for ATS
#     - Common mistakes to avoid
#     - Industry-specific formatting suggestions
#     """
    
#     try:
#         model = genai.GenerativeModel('gemini-1.5-flash')
#         response = model.generate_content([prompt])
#         return {
#             "success": True,
#             "tips": response.text.strip(),
#             "role": target_role
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error generating tips: {str(e)}")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)