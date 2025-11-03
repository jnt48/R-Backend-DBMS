from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import oracledb
import hashlib
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

# Groq AI Configuration
GROQ_API_KEY = "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"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

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

class ChatRequest(BaseModel):
    message: str
    case_id: Optional[int] = None
    context: Optional[str] = None

class DocumentVerify(BaseModel):
    document_hash: str

class StatusUpdate(BaseModel):
    status: str


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
            "model": "llama-3.3-70b-versatile",
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