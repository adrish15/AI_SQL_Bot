import streamlit as st
from sqlalchemy import text
import pandas as pd # if you plan to integrate real AI
import llm_compute

st.set_page_config(page_title="AI SQL Chatbot", page_icon="🤖", layout="wide")
st.title("🤖 AI SQL Chatbot")

# Ensure engine is passed via session_state
if "engine" not in st.session_state:
    st.warning("❗ No database connection found. Please go back to the **Database Connection Setup** page and connect first.")
    st.stop()

engine = st.session_state["engine"]
if "thread_id" not in st.session_state:
    st.session_state.thread_id = 1  # initialize if not present


# Initialize chat history
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []


# Display chat history
for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Accept user input
if prompt := st.chat_input("Ask me to run SQL queries in natural language"):
    # Add user message
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        # Placeholder SQL generation
        # Replace this with your AI logic later (e.g., call OpenAI GPT)
        def generate_sql(question: str,id) -> str:
            return llm_compute.query_agent(question,id)
        
        with st.spinner("Generating Answer..."):
            sql = generate_sql(prompt, int(st.session_state["thread_id"]))

        # Show results
        with st.chat_message("assistant"):
            st.info(sql)
            st.session_state.chat_messages.append({"role": "assistant", "content": sql})
    except Exception as e:
        error_msg = f"Error: {e}"
        with st.chat_message("assistant"):
            st.error(error_msg)
        st.session_state.chat_messages.append({"role": "assistant", "content": error_msg})

# ✅ Bottom container for fixed "New Chat" button
with st.container():
    if st.session_state.chat_messages:  # only show if chat exists
        if st.button("🆕 New Chat", use_container_width=True):
            st.session_state.chat_messages = []
            st.session_state.thread_id += 1  # increment if already exists
            st.rerun()
