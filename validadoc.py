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

# Inicialização do estado da sessão
if "sessao_encerrada" not in st.session_state:
    st.session_state.sessao_encerrada = False

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# --- TELA DE SESSÃO ENCERRADA ---
if st.session_state.sessao_encerrada:
    st.title("📋 Validador de Documentos")
    st.info("👋 Sessão encerrada com sucesso. Obrigado por utilizar o validador!")
    
    if st.button("Nova Consulta / Iniciar Novamente", type="primary"):
        st.session_state.sessao_encerrada = False
        st.session_state.uploader_key += 1
        st.rerun()
    st.stop()

st.title("📋 Validador de Documentos")
st.write("Faça upload do documento para validar as informações.")

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

def formatar_cnpj(cnpj: str) -> str:
    """Formata os 14 dígitos no padrão XX.XXX.XXX/XXXX-XX."""
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"

# --- INTERFACE E FLUXO PRINCIPAL ---

arquivo = st.file_uploader(
    "Anexe o documento (PDF, JPG, JPEG, PNG, TXT, XLS, XLSM)",
    type=["pdf", "jpg", "jpeg", "png", "txt", "xls", "xlsm", "xlsx"],
    key=f"uploader_{st.session_state.uploader_key}"
)

if arquivo is not None:
    with st.spinner("Lendo e processando o documento..."):
        conteudo_texto = ler_arquivo(arquivo)
        cnpjs_encontrados = extrair_cnpjs_de_texto(conteudo_texto)

        # Identificação silenciosa do documento
        eh_consolida_precos = (
            "CONSOLIDACAO DE PESQUISAS DE PRECOS" in conteudo_texto.upper() or 
            "CONSOLIDAÇÃO DE PESQUISAS DE PREÇOS" in conteudo_texto.upper()
        )

    st.divider()

    # RESULTADOS DA VALIDAÇÃO NA RECEITA FEDERAL
    if not cnpjs_encontrados:
        st.warning("⚠️ Nenhum CNPJ válido foi encontrado no arquivo anexado.")
    else:
        for cnpj in cnpjs_encontrados:
            dados = consultar_receita_federal(cnpj)

            if "erro" in dados:
                cnpj_formatado = formatar_cnpj(cnpj)
                with st.expander(f"🔍 CNPJ: {cnpj_formatado}", expanded=True):
                    st.error(f"❌ **CNPJ {cnpj_formatado}:** {dados['erro']}")
            else:
                razao_social_oficial = dados.get("razao_social", "N/A")

                # FILTRO: Se for "Conselho de Escola", ignora e não exibe na tela
                if "CONSELHO DE ESCOLA" in razao_social_oficial.upper():
                    continue

                cnpj_formatado = formatar_cnpj(cnpj)
                situacao = dados.get("descricao_situacao_cadastral", "DESCONHECIDA")
                nome_fantasia = dados.get("nome_fantasia") or "Não informado"
                uf = dados.get("uf", "")
                municipio = dados.get("municipio", "")

                with st.expander(f"🔍 CNPJ: {cnpj_formatado}", expanded=True):
                    if situacao.upper() == "ATIVO":
                        st.success(f"**Situação Cadastral:** {situacao}")
                    else:
                        st.warning(f"**Situação Cadastral:** {situacao}")

                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Razão Social Oficial:** {razao_social_oficial}")
                        st.write(f"**Nome Fantasia:** {nome_fantasia}")
                    with col2:
                        st.write(f"**Cidade/UF:** {municipio} - {uf}")
                        st.write(f"**Atividade Principal:** {dados.get('cnae_fiscal_descricao', 'N/A')}")

    # --- BOTÕES DE NAVEGAÇÃO E ENCERRAMENTO ---
    st.divider()
    btn_col1, btn_col2 = st.columns(2)
    
    with btn_col1:
        if st.button("⬅️ Voltar (Nova Validação)", use_container_width=True):
            st.session_state.uploader_key += 1
            st.rerun()

    with btn_col2:
        if st.button("🔴 Sair", use_container_width=True):
            st.session_state.sessao_encerrada = True
            st.rerun()
