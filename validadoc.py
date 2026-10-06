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

# --- VALIDAÇÃO MATEMÁTICA DE CNPJ (MÓDULO 11) ---

def validar_digitos_cnpj(cnpj: str) -> bool:
    """Valida se uma string de 14 dígitos numéricos é um CNPJ matematicamente válido."""
    cnpj = re.sub(r'\D', '', str(cnpj))
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False

    def calcular_digito(fatia, pesos):
        soma = sum(int(a) * b for a, b in zip(fatia, pesos))
        resto = soma % 11
        return '0' if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    digito1 = calcular_digito(cnpj[:12], pesos1)
    digito2 = calcular_digito(cnpj[:12] + digito1, pesos2)

    return cnpj[-2:] == digito1 + digito2

# --- FUNÇÃO DE CLASSIFICAÇÃO DO DOCUMENTO ---

def identificar_tipo_documento(texto: str) -> str:
    """Classifica o documento com base em palavras-chave encontradas no texto."""
    texto_upper = texto.upper()

    if "CONSOLIDACAO DE PESQUISAS DE PRECOS" in texto_upper or "CONSOLIDAÇÃO DE PESQUISAS DE PREÇOS" in texto_upper or "BLOCO I - IDENTIFICAÇÃO" in texto_upper:
        return "Consolidação de Pesquisas de Preços"
    
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

# --- EXTRAÇÃO DE TEXTO E CNPJ ---

def corrigir_substituicoes_ocr(string_cand: str) -> str:
    mapeamento = {
        'O': '0', 'o': '0', 'D': '0',
        'I': '1', 'l': '1', 'L': '1',
        'Z': '2',
        'S': '5', 's': '5',
        'G': '6',
        'B': '8'
    }
    return "".join([mapeamento.get(char, char) for char in string_cand])

def extrair_cnpjs_de_texto(texto: str) -> list:
    cnpjs_validos = set()

    padrao_cnpj = r'\b[0-9OoDDIlLZSsGGB]{2}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[/\s]?[0-9OoDDIlLZSsGGB]{4}[-\s]?[0-9OoDDIlLZSsGGB]{2}\b'
    for c in re.findall(padrao_cnpj, texto):
        c_corrigido = corrigir_substituicoes_ocr(c)
        num = re.sub(r'\D', '', c_corrigido)
        if len(num) == 14 and validar_digitos_cnpj(num):
            cnpjs_validos.add(num)

    texto_limpo = corrigir_substituicoes_ocr(texto)
    apenas_numeros = re.sub(r'\D', ' ', texto_limpo)
    for bloco in apenas_numeros.split():
        if len(bloco) >= 14:
            for i in range(len(bloco) - 13):
                cand = bloco[i:i+14]
                if len(cand) == 14 and validar_digitos_cnpj(cand):
                    cnpjs_validos.add(cand)

    return list(cnpjs_validos)

def ler_arquivo(uploaded_file) -> str:
    extensao = uploaded_file.name.split('.')[-1].lower()
    texto_extraido = ""

    try:
        if extensao in ['jpg', 'jpeg', 'png']:
            imagem = Image.open(uploaded_file)
            texto_extraido += pytesseract.image_to_string(imagem, lang='por') + "\n"
            
            img_cinza = imagem.convert('L')
            enhancer = ImageEnhance.Contrast(img_cinza)
            img_contraste = enhancer.enhance(2.5)
            texto_extraido += pytesseract.image_to_string(img_contraste, lang='por') + "\n"
            texto_extraido += pytesseract.image_to_string(img_contraste, lang='por', config='--psm 6') + "\n"

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
                        img_cinza = img.convert('L')
                        enhancer = ImageEnhance.Contrast(img_cinza)
                        img_contraste = enhancer.enhance(2.5)
                        texto_extraido += pytesseract.image_to_string(img_contraste, lang='por') + "\n"

        elif extensao == 'txt':
            texto_extraido = uploaded_file.read().decode('utf-8', errors='ignore')

        elif extensao in ['xls', 'xlsm', 'xlsx']:
            df_dict = pd.read_excel(uploaded_file, sheet_name=None)
            for nome_aba, aba in df_dict.items():
                texto_extraido += f" {aba.to_string()} "

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")

    return texto_extraido

# --- CONSULTA À RECEITA FEDERAL COM API DE CONTINGÊNCIA ---

@st.cache_data(ttl=3600)
def consultar_receita_federal(cnpj: str) -> dict:
    """Consulta a BrasilAPI e usa a ReceitaWS como contingência caso ocorra erro no servidor."""
    cnpj_limpo = re.sub(r'\D', '', str(cnpj))
    
    # 1. Tentativa Principal: BrasilAPI
    url_brasil_api = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    try:
        response = requests.get(url_brasil_api, timeout=8)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {"erro": "CNPJ não encontrado na base da Receita Federal."}
    except requests.RequestException:
        pass

    # 2. Contingência: ReceitaWS (caso a BrasilAPI retorne 500 ou falhe a ligação)
    url_receitaws = f"https://receitaws.com.br/v1/cnpj/{cnpj_limpo}"
    try:
        response_alt = requests.get(url_receitaws, timeout=8)
        if response_alt.status_code == 200:
            dados_alt = response_alt.json()
            if dados_alt.get("status") != "ERROR":
                return {
                    "razao_social": dados_alt.get("nome", "N/A"),
                    "nome_fantasia": dados_alt.get("fantasia", "Não informado"),
                    "descricao_situacao_cadastral": dados_alt.get("situacao", "DESCONHECIDA"),
                    "uf": dados_alt.get("uf", ""),
                    "municipio": dados_alt.get("municipio", ""),
                    "cnae_fiscal_descricao": dados_alt.get("atividade_principal", [{}])[0].get("text", "N/A")
                }
    except requests.RequestException:
        pass

    return {"erro": "A API da Receita Federal está instável no momento. Tente novamente em alguns instantes."}

def formatar_cnpj(cnpj: str) -> str:
    c = re.sub(r'\D', '', str(cnpj))
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"

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

    st.subheader("📄 Tipo de Documento")
    if tipo_documento != "Documento Genérico / Não Identificado":
        st.success(f"**{tipo_documento}**")
    else:
        st.info(f"**{tipo_documento}**")

    if tipo_documento != "Documento Genérico / Não Identificado":
        st.divider()
        st.subheader("🔍 Validação na Receita Federal")

        # Filtra previamente o CNPJ do Conselho de Escola
        cnpjs_para_exibir = [c for c in cnpjs_encontrados if re.sub(r'\D', '', c) != "06697670000195"]

        if not cnpjs_para_exibir:
            st.warning("⚠️ Nenhum CNPJ de fornecedor/emitente válido foi encontrado no arquivo anexado.")
        else:
            for cnpj in cnpjs_para_exibir:
                dados = consultar_receita_federal(cnpj)
                cnpj_formatado = formatar_cnpj(cnpj)

                if isinstance(dados, dict) and "erro" in dados:
                    with st.expander(f"CNPJ: {cnpj_formatado}", expanded=True):
                        st.error(f"❌ **CNPJ {cnpj_formatado}:** {dados['erro']}")
                else:
                    razao_social_oficial = dados.get("razao_social", "N/A")

                    if "CONSELHO DE ESCOLA" in razao_social_oficial.upper():
                        continue

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

    st.session_state.validado = True

    st.divider()
    if st.button("⬅️ Voltar (Nova Validação)", use_container_width=True):
        st.session_state.validado = False
        st.session_state.uploader_key += 1
        st.rerun()
