import streamlit as st
from sqlalchemy import create_engine, text
import sqlalchemy
from llm_compute import build_schema_profile, setup_agent
import tempfile
import sqlite3
from sqlalchemy.pool import StaticPool

# Title with emoji
st.set_page_config(page_title="Database Connector", page_icon="🗄️", layout="centered")
st.title("🗄️ Database Connection Setup")

st.markdown("Easily connect to **MySQL, PostgreSQL, SQLite, or Oracle** databases from here.")

# Dropdown for DB type
db_type = st.selectbox(
    "📂 Select Database Type",
    ["MySQL", "PostgreSQL", "SQLite", "Oracle"]
)

def filled(x):
    return bool(x and str(x).strip())

def sqllite_engine(sqlite_upload):
        # Save upload temporarily
        tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmpfile.write(sqlite_upload.read())
        tmpfile.flush()
        tmpfile.close()

        # Load into in-memory DB
        disk_conn = sqlite3.connect(tmpfile.name, check_same_thread=False)
        mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        with mem_conn:
            for line in disk_conn.iterdump():
                mem_conn.execute(line)
        disk_conn.close()

        # Wrap the same in-memory connection in SQLAlchemy
        engine = create_engine(
            "sqlite://",
            creator=lambda: mem_conn,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )

        st.session_state["engine"] = engine
        st.success("✅ SQLite DB loaded into in-memory engine!")

# Input form
with st.form("db_form", clear_on_submit=False):
    hostname = port = username = password = database_name = sqlite_file = None
    
    if db_type in ["MySQL", "PostgreSQL", "Oracle"]:
        col1, col2 = st.columns(2)
        with col1:
            hostname = st.text_input("🌐 Hostname", value="localhost")
            username = st.text_input("👤 Username")
            database_name = st.text_input("📦 Database Name")
        with col2:
            port = st.text_input("🔌 Port", 
                value="3306" if db_type == "MySQL" else 
                      "5432" if db_type == "PostgreSQL" else 
                      "1521")
            password = st.text_input("🔑 Password", type="password")
    elif db_type == "SQLite":
        sqlite_upload = st.file_uploader("📂 Upload SQLite DB file", type=["db", "sqlite"])
    
    # Submit button
    submitted = st.form_submit_button("🚀 Connect")

# Check readiness
if submitted:
    try:
        if db_type == "SQLite":
            if sqlite_upload is None:
                st.warning("⚠️ Please upload a valid SQLite database file.")
                st.stop()
            sqllite_engine(sqlite_upload)
        else:
            if not all([filled(hostname), filled(port), filled(username), filled(password), filled(database_name)]):
                st.warning("⚠️ Please fill in all fields before connecting.")
                st.stop()
            
            if db_type == "MySQL":
                database_url = f"mysql+mysqlconnector://{username}:{password}@{hostname}:{port}/{database_name}"
            elif db_type == "PostgreSQL":
                database_url = f"postgresql+psycopg2://{username}:{password}@{hostname}:{port}/{database_name}"
            elif db_type == "Oracle":
                database_url = sqlalchemy.engine.URL.create(
                    "oracle+oracledb",
                    username=username,
                    password=password,
                    host=hostname,
                    port=int(port),
                    query={"service_name": database_name},
                )
            # Connect
            st.session_state["engine"] = create_engine(database_url)

        with st.session_state["engine"].connect() as connection:
            cursor = connection.execute(text("SELECT 1"))
        schema_profile = build_schema_profile(st.session_state["engine"])
        st.session_state["schema_profile"] = schema_profile
        st.session_state["agent"] = setup_agent(
            dialect=db_type.lower(),
            engine=st.session_state["engine"],
            schema_profile=schema_profile,
        )
        st.success(f"✅ Successfully connected to **{db_type}** database!")
    
    except Exception as e:
        st.error(f"❌ Error connecting to database:\n\n{e}")
