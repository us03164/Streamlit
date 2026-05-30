
import traceback
import streamlit as st
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

# 1. 프롬프트 개선 (출력 형식을 조금 더 명확하게 지시)
SUMMARIZE_PROMPT = """다음 제공된 콘텐츠의 핵심 내용을 약 300자 내외로 알기 쉽게 요약해주세요.
반드시 한국어로 자연스럽게 작성해야 합니다.

========
{content}
========
"""

def init_page():
    st.set_page_config(page_title="웹 사이트 요약기", page_icon="🤗")
    st.header("웹 사이트 요약기 🤗")
    st.sidebar.title("Options")

def select_model(temperature = 0):
    models = ("gpt-5.5", "gpt-5.4-mini")
    model = st.sidebar.radio("Choose a model:", models)
    if model == 'gpt-5.5':
        return ChatOpenAI(temperature = temperature, model = 'gpt-5.5')
    else:
        return ChatOpenAI(temperature = temperature, model = 'gpt-5.4-mini')

def init_chain():
    llm = select_model()
    prompt = ChatPromptTemplate.from_messages([
        ('user', SUMMARIZE_PROMPT)])
    chain = prompt | llm | StrOutputParser()
    return chain

def get_content(url):
    with st.spinner('웹 사이트 정보 찾는중...'):
        url = requests.get(url)
        html = BeautifulSoup(url.text)
        if html.main:
            return html.main.text
        elif html.article:
            return html.article.text
        else:
            return html.body.text

def main():
    init_page()
    chain = init_chain()
    if url := st.text_input("URL: ", key = 'input'):
        if content := get_content(url):
            st.markdown("## Summary")
            st.write_stream(chain.stream({'content' : content}))
            st.markdown("-----")
            st.markdown("## Original Text")
            st.write(content)

main()
