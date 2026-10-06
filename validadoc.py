import streamlit as st
import re
import requests
import pandas as pd
import pdfplumber
from PIL import Image, ImageEnhance
import pytesseract

# Configuração da página
st.set_page_config(page_title="Validador de Documentos", page_icon="📋", layout="wide")

# Inicialização do estado da sessão
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "validado" not in st.session_state:
    st.session_state.validado = False

# --- OCULTAR ELEMENTOS PADRÃO DO STREAMLIT ---
estilo_css = """
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .stAppHeader {display: none;}
"""

# Oculta a área de upload após o término completo da validação
if st.session_state.validado:
    estilo_css += """
    div[data-testid="stFileUploader"] {
        display: none !important;
    }
    """

estilo_css += " </style>"
st.markdown(estilo_css, unsafe_allow_html=True)

st.title("📋 Validador de Documentos")
st.write("Faça upload do documento para identificar o tipo e validar os CNPJs na Receita Federal.")

# --- FUNÇÃO DE CLASSIFICAÇÃO DO DOCUMENTO ---

def identificar_tipo_documento(texto: str) -> str:
    """Classifica o documento com base em palavras-chave encontradas no texto."""
    texto_upper = texto.upper()

    # 1. Consolidação de Pesquisas de Preços
    if "CONSOLIDACAO DE PESQUISAS DE PRECOS" in texto_upper or "CONSOLIDAÇÃO DE PESQUISAS DE PREÇOS" in texto_upper or "BLOCO I - IDENTIFICAÇÃO" in texto_upper:
        return "Consolidação de Pesquisas de Preços"
    
    # 2. Nota Fiscal de Serviços (NFS-e / Municipal)
    elif (
        "NOTA FISCAL DE SERVICOS" in texto_upper or 
        "NOTA FISCAL DE SERVIÇOS" in texto_upper or 
        "NOTA FISCAL ELETRÔNICA DE SERVIÇO" in texto_upper or 
        "NOTA FISCAL ELETRONICA DE SERVICO" in texto_upper or 
        "NFS-E" in texto_upper or 
        "NFSE" in texto_upper or 
        "PRESTADOR DE SERVIÇOS" in texto_upper or 
        "PRESTADOR DE SERVICOS" in texto_upper or 
        "TOMADOR DE SERVIÇOS" in texto_upper or 
        "TOMADOR DE SERVICOS" in texto_upper or 
        "DISCRIMINAÇÃO DOS SERVIÇOS" in texto_upper or 
        "DISCRIMINACAO DOS SERVICOS" in texto_upper or 
        "VALOR DOS SERVIÇOS" in texto_upper or 
        "VALOR DOS SERVICOS" in texto_upper or 
        "SECRETARIA DE FINANÇAS" in texto_upper or 
        "SECRETARIA DE FINANCAS" in texto_upper or 
        "ISSQN" in texto_upper
    ):
        return "Nota Fiscal de Serviços"
    
    # 3. Nota Fiscal de Compra de Materiais (DANFE / NF-e / Venda de Mercadoria)
    elif (
        "DANFE" in texto_upper or 
        "DOCUMENTO AUXILIAR DA NOTA FISCAL" in texto_upper or 
        "VENDA DE MERCADORIA" in texto_upper or 
        "NFE" in texto_upper or 
        "NF-E" in texto_upper or 
        "CHAVE DE ACESSO" in texto_upper or 
        "DADOS DOS PRODUTOS" in texto_upper
    ):
        return "Nota Fiscal de Compra de Materiais"
    
    else:
        return "Documento Genérico / Não Identificado"

# --- FUNÇÕES DE EXTRAÇÃO DE TEXTO E CNPJ ---

def extrair_cnpjs_de_texto(texto: str) -> list:
    """Busca padrões de CNPJ no texto com substituição de ruídos de OCR."""
    cnpjs_limpos = set()

    # 1. Busca por padrões tradicionais de CNPJ (com ou sem pontuação)
    padrao_cnpj = r'\b\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[/\s]?\d{4}[-\s]?\d{2}\b'
    encontrados = re.findall(padrao_cnpj, texto)
    for c in encontrados:
        num = re.sub(r'\D', '', c)
        if len(num) == 14:
            cnpjs_limpos.add(num)

    # 2. Tratamento para falhas comuns de OCR (substitui 'O/o' por '0', 'I/l' por '1')
    texto_trabalhado = texto.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')
    encontrados_trabalhados = re.findall(padrao_cnpj, texto_trabalhado)
    for c in encontrados_trabalhados:
        num = re.sub(r'\D', '', c)
        if len(num) == 14:
            cnpjs_limpos.add(num)

    # 3. Varredura direta em sequências numéricas continuas
    apenas_numeros = re.sub(r'\D', ' ', texto_trabalhado)
    for bloco in apenas_numeros.split():
        if len(bloco) >= 14:
            for i in range(len(bloco) - 13):
                cand = bloco[i:i+14]
                if len(cand) == 14:
                    cnpjs_limpos.add(cand)

    return list(cnpjs_limpos)

def ler_arquivo(uploaded_file) -> str:
    """Lê o arquivo anexado dependendo da extensão e retorna o texto extraído."""
    extensao = uploaded_file.name.split('.')[-1].lower()
    texto_extraido = ""

    try:
        if extensao in ['jpg', 'jpeg', 'png']:
            imagem = Image.open(uploaded_file)
            
            # Leitura OCR Padrão
            texto_extraido = pytesseract.image_to_string(imagem, lang='por')
            
            # Se a leitura inicial for fraca, tenta com ajuste simples de contraste
            if len(texto_extraido.strip()) < 40:
                imagem_cinza = imagem.convert('L')
                enhancer = ImageEnhance.Contrast(imagem_cinza)
                imagem_contraste = enhancer.enhance(2.0)
                texto_extraido += "\n" + pytesseract.image_to_string(imagem_contraste, lang='por')

        elif extensao == 'pdf':
            with pdfplumber.open(uploaded_file) as pdf:
                for pagina in pdf.pages:
                    t = pagina.extract_text()
                    if t:
                        texto_extraido += t + "\n"
                        
            # Se for PDF de imagem (scaneado sem camada de texto)
            if not texto_extraido.strip():
                uploaded_file.seek(0)
                with pdfplumber.open(uploaded_file) as pdf:
                    for pagina in pdf.pages:
                        img = pagina.to_image().original
                        texto_extraido += pytesseract.image_to_string(img, lang='por') + "\n"

        elif extensao == 'txt':
            texto_extraido = uploaded_file.read().decode('utf-8', errors='ignore')

        elif extensao in ['xls', 'xlsm', 'xlsx']:
            df_dict = pd.read_excel(uploaded_file, sheet_name=None)
            for nome_aba, aba in df_dict.items():
                texto_extraido += f" {aba.to_string()} "

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")

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
        tipo_documento = identificar_tipo_documento(conteudo_texto)

    st.divider()

    # 1. IDENTIFICAÇÃO DO TIPO DE DOCUMENTO
    st.subheader("📄 Tipo de Documento")
    if tipo_documento != "Documento Genérico / Não Identificado":
        st.success(f"**{tipo_documento}**")
    else:
        st.info(f"**{tipo_documento}**")

    st.divider()

    # 2. RESULTADOS DA VALIDAÇÃO NA RECEITA FEDERAL
    st.subheader("🔍 Validação na Receita Federal")

    if not cnpjs_encontrados:
        st.warning("⚠️ Nenhum CNPJ válido foi encontrado no arquivo anexado.")
    else:
        for cnpj in cnpjs_encontrados:
            dados = consultar_receita_federal(cnpj)

            if "erro" in dados:
                cnpj_formatado = formatar_cnpj(cnpj)
                with st.expander(f"CNPJ: {cnpj_formatado}", expanded=True):
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

                with st.expander(f"CNPJ: {cnpj_formatado}", expanded=True):
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

    # Marca a validação como concluída ao FINAL do processamento
    if not st.session_state.validado:
        st.session_state.validado = True
        st.rerun()

    # --- BOTÃO DE NAVEGAÇÃO ---
    st.divider()
    if st.button("⬅️ Voltar (Nova Validação)", use_container_width=True):
        st.session_state.validado = False
        st.session_state.uploader_key += 1
        st.rerun()
