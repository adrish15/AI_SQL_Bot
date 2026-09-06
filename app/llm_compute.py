import os
import json
import re
from dotenv import load_dotenv
import streamlit as st
from langchain.chat_models import init_chat_model
from sqlalchemy import inspect, text
from prompt_factory import system_prompt
import pandas as pd

load_dotenv()

if not os.environ.get("GOOGLE_API_KEY"):
  os.environ["GOOGLE_API_KEY"] = input("enter your Google API key: ")

llm=init_chat_model(model="gemini-3.5-flash-lite", model_provider="google_genai",temperature=0.0)

def build_schema_profile(engine):
    """Create a compact schema snapshot once, immediately after connecting."""
    database_inspector = inspect(engine)
    tables = []
    for table_name in database_inspector.get_table_names():
        columns = [
            f"{column['name']} ({column['type']})"
            for column in database_inspector.get_columns(table_name)
        ]
        foreign_keys = [
            f"{key['constrained_columns']} -> {key['referred_table']}.{key['referred_columns']}"
            for key in database_inspector.get_foreign_keys(table_name)
        ]
        tables.append({
            "name": table_name,
            "columns": columns,
            "foreign_keys": foreign_keys,
        })
    return {"dialect": engine.dialect.name, "tables": tables}


def setup_agent(dialect, engine, schema_profile):
    """Keep the connection context used by the staged query agents."""
    return {
        "dialect": dialect,
        "engine": engine,
        "schema_profile": schema_profile,
    }


def _content(response):
    value = response.content if hasattr(response, "content") else response
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in value
            if isinstance(block, str) or isinstance(block, dict)
        )
    return str(value)


def _json_response(response):
    raw = _content(response).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Agent returned invalid JSON: {raw}")
    return json.loads(match.group(0))


def _profile_text(profile):
    return json.dumps(profile, default=str, indent=2)


def _conversation_text(messages):
    return "\n".join(
        f"{message['role'].upper()}: {message['content']}"
        for message in messages[-12:]
    )


def _route(query, profile, conversation):
    response = llm.invoke(f"""
You are the routing agent for a database assistant. Return JSON only with keys:
"mode" and "reason". The mode must be exactly "data" or "conversation".
Choose "data" only when the user needs new facts, counts, rows, calculations, or
database filtering that requires executing SQL. Choose "conversation" for greetings,
thanks, explanations of database terms, explanations of a previous answer or SQL,
clarifications about assumptions, and related questions answerable from the schema or
conversation history without querying rows.
Schema:
{_profile_text(profile)}
Conversation history:
{conversation}
Current request: {query}
""")
    return _json_response(response)


def _conversation_answer(query, profile, conversation):
    return _content(llm.invoke(f"""
You are the conversational assistant for a database chatbot. Answer the user's
question directly and naturally using the schema and conversation history. Explain
terms, assumptions, previous SQL, and previous answers when asked. Do not generate or
run SQL for this response. Do not claim database facts that are not present in the
conversation or schema. If answering requires fresh database values, say that a data
query is needed instead. Explain the reasoning clearly and include relevant context,
definitions, and assumptions without adding unrelated detail.
Schema:
{_profile_text(profile)}
Conversation history:
{conversation}
User request: {query}
"""))


def _clarify(query, profile, conversation):
    response = llm.invoke(f"""
You are the clarification agent for a database assistant.
Return JSON only: {{"needs_clarification": true|false, "question": "..."}}.
Ask one concise question only when the request has an important ambiguity.
Otherwise return needs_clarification false and an empty question.
Database schema:
{_profile_text(profile)}
Conversation history:
{conversation}
User request: {query}
""")
    return _json_response(response)


def _plan(query, profile, conversation, previous_error=""):
    response = llm.invoke(f"""
You are the query planning agent. Return JSON only with keys: sql, plan, assumptions.
Write one read-only {profile['dialect']} SQL query. Never use INSERT, UPDATE, DELETE,
DROP, ALTER, CREATE, or other DDL/DML. Use only tables and columns in the schema.
Limit detail rows to 50 unless the user requests another number.
Schema:
{_profile_text(profile)}
Conversation history:
{conversation}
User request: {query}
Previous execution error, if any: {previous_error}
""")
    return _json_response(response)


def _critic(plan, profile, conversation):
    response = llm.invoke(f"""
You are a SQL critic. Return JSON only with keys: approved, sql, issues.
Check the SQL for read-only safety, valid schema references, joins, aggregation,
filters, and whether it answers the request. Set approved false when it needs repair.
Schema:
{_profile_text(profile)}
Conversation history:
{conversation}
Plan:
{json.dumps(plan, default=str)}
""")
    return _json_response(response)


def _is_read_only(sql):
    statements = [part.strip() for part in sql.split(";") if part.strip()]
    if len(statements) != 1:
        return False
    return not re.match(r"^(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE)\b", statements[0], re.IGNORECASE)


def query_agent(query, id):
    agent = st.session_state["agent"]
    profile = agent["schema_profile"]
    conversation = _conversation_text(st.session_state.get("chat_messages", []))
    pending_query = st.session_state.pop("pending_query", None)
    if pending_query:
        query = f"Original request: {pending_query}\nClarification answer: {query}"
        conversation = f"{conversation}\nUSER: {query}"
    else:
        route = _route(query, profile, conversation)
        if route.get("mode") == "conversation":
            return _conversation_answer(query, profile, conversation)
    clarification = _clarify(query, profile, conversation)
    if clarification.get("needs_clarification"):
        st.session_state["pending_query"] = query
        return f"CLARIFICATION: {clarification['question']}"

    last_error = ""
    for attempt in range(3):
        plan = _plan(query, profile, conversation, last_error)
        critique = _critic(plan, profile, conversation)
        if not critique.get("approved"):
            last_error = "; ".join(critique.get("issues", []))
            continue
        sql = critique.get("sql", plan.get("sql", "")).strip()
        if not _is_read_only(sql):
            last_error = "The proposed SQL was rejected because it is not a single read-only statement."
            continue
        try:
            results = pd.read_sql_query(text(sql), agent["engine"])
        except Exception as error:
            last_error = str(error)
            continue

        preview = results.head(50).to_json(orient="records", date_format="iso")
        sanity = _json_response(llm.invoke(f"""
You are the result sanity-check agent. Return JSON only with keys: valid, issue.
Mark valid false if the result is empty unexpectedly, clearly duplicated, or does not
support the user's question. Do not invent facts.
Question: {query}
Conversation history:
{conversation}
SQL: {sql}
Rows returned: {len(results)}
Result preview: {preview}
"""))
        if not sanity.get("valid", False):
            last_error = sanity.get("issue", "The result failed validation.")
            continue

        answer = _content(llm.invoke(f"""
Answer the user's database question using only these query results. Be concise and
include the SQL used plus a short note about any assumptions.
Question: {query}
Conversation history:
{conversation}
Plan: {plan.get('plan', '')}
SQL: {sql}
Results: {preview}
"""))
        return answer

    return f"I could not produce a verified read-only answer after three attempts. Last issue: {last_error}"
