import streamlit as st
import re
import requests
import json
import pandas as pd
import pdfplumber
from PIL import Image
import pytesseract

# Configuração da página
st.set_page_config(page_title="Validador de Documentos", page_icon="📋", layout="wide")

# --- OCULTAR ELEMENTOS E MARCA DO STREAMLIT ---
ocultar_elementos_streamlit = """
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .stAppHeader {display: none;}
    </style>
"""
st.markdown(ocultar_elementos_streamlit, unsafe_allow_html=True)

st.title("📋 Validador de Documentos")
st.write("Faça upload do documento para extrair e consultar os CNPJs na Receita Federal.")

# --- FUNÇÕES DE EXTRAÇÃO DE TEXTO ---

def extrair_cnpjs_de_texto(texto: str) -> list:
    """Busca padrões de CNPJ (com ou sem formatação) no texto."""
    padrao = r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b'
    encontrados = re.findall(padrao, texto)
    
    cnpjs_limpos = set()
    for c in encontrados:
        numeros = re.sub(r'\D', '', c)
        if len(numeros) == 14:
            cnpjs_limpos.add(numeros)
            
    return list(cnpjs_limpos)

def ler_arquivo(uploaded_file) -> str:
    """Lê o arquivo anexado dependendo da extensão e retorna o texto extraído."""
    extensao = uploaded_file.name.split('.')[-1].lower()
    texto_extraido = ""

    try:
        if extensao in ['jpg', 'jpeg', 'png']:
            imagem = Image.open(uploaded_file)
            texto_extraido = pytesseract.image_to_string(imagem, lang='por')

        elif extensao == 'pdf':
            with pdfplumber.open(uploaded_file) as pdf:
                for pagina in pdf.pages:
                    t = pagina.extract_text()
                    if t:
                        texto_extraido += t + "\n"
            if not texto_extraido.strip():
                uploaded_file.seek(0)
                with pdfplumber.open(uploaded_file) as pdf:
                    for pagina in pdf.pages:
                        img = pagina.to_image().original
                        texto_extraido += pytesseract.image_to_string(img, lang='por') + "\n"

        elif extensao == 'txt':
            texto_extraido = uploaded_file.read().decode('utf-8', errors='ignore')

        elif extensao in ['xls', 'xlsm', 'xlsx']:
            df = pd.read_excel(uploaded_file, sheet_name=None)
            for nome_aba, aba in df.items():
                texto_extraido += f" {aba.to_string()} "

    except Exception as e:
        st.error(f"Erro ao ler o arquivo: {e}")

    return texto_extraido

# --- FUNÇÃO DE CONSULTA À RECEITA FEDERAL ---

@st.cache_data(ttl=3600)
def consultar_receita_federal(cnpj: str) -> dict:
    """Consulta a API pública 'BrasilAPI' para obter dados da Receita Federal."""
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {"erro": "CNPJ não encontrado na base da Receita Federal."}
        else:
            return {"erro": f"Erro na consulta (Código {response.status_code})."}
    except requests.RequestException:
        return {"erro": "Falha de conexão com a API da Receita Federal."}

def formatar_cnpj(cnpj: str
