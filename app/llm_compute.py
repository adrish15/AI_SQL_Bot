import os
from dotenv import load_dotenv
import streamlit as st
from langchain.chat_models import init_chat_model
from langchain_core.prompts import PromptTemplate
from prompt_factory import system_prompt
from langgraph.prebuilt import create_react_agent
from langchain.agents.agent_toolkits import create_retriever_tool
from langchain_community.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import pandas as pd
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langgraph.checkpoint.memory import MemorySaver
from langchain_community.utilities.sql_database import SQLDatabase

load_dotenv()

if not os.environ.get("GOOGLE_API_KEY"):
  os.environ["GOOGLE_API_KEY"] = input("enter your Google API key: ")

llm=init_chat_model(model="gemini-2.5-flash", model_provider="google_genai",temperature=0.0)

system_prompt=PromptTemplate.from_template(system_prompt)

def setup_agent(dialect,engine):
    db=SQLDatabase(engine)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools=toolkit.get_tools()
    #tools.append(table_info_tool)
    return create_react_agent(model=llm,
                    prompt=system_prompt.invoke({'dialect':dialect,'top_k':'5'}).to_string(),checkpointer=MemorySaver(),tools=tools)

def query_agent(query,id):
    config = {"configurable": {"thread_id": id}}
    response = st.session_state["agent"].invoke(
    {"messages": [{"role": "user", "content": query}]},
    config=config
    )
    return response["messages"][-1].content
