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

# --- VALIDAÇÃO MATEMÁTICA DE CNPJ (MÓDULO 11) ---

def validar_digitos_cnpj(cnpj: str) -> bool:
    """Valida se uma string de 14 dígitos numéricos é um CNPJ matematicamente válido."""
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

def corrigir_substituicoes_ocr(string_cand: str) -> str:
    """Corrige trocas de letras por números típicas em leituras de fotos/impressões."""
    mapeamento = {
        'O': '0', 'o': '0', 'D': '0',
        'I': '1', 'l': '1', 'L': '1',
        'Z': '2',
        'S': '5', 's': '5',
        'G': '6',
        'B': '8'
    }
    res = []
    for char in string_cand:
        res.append(mapeamento.get(char, char))
    return "".join(res)

def extrair_cnpjs_de_texto(texto: str) -> list:
    """Busca padrões de CNPJ no texto e aplica autocorreção de ruídos de OCR."""
    cnpjs_validos = set()

    # 1. Padrão tradicional com pontuação/espaço
    padrao_cnpj = r'\b[0-9OoDDIlLZSsGGB]{2}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[/\s]?[0-9OoDDIlLZSsGGB]{4}[-\s]?[0-9OoDDIlLZSsGGB]{2}\b'
    for c in re.findall(padrao_cnpj, texto):
        c_corrigido = corrigir_substituicoes_ocr(c)
        num = re.sub(r'\D', '', c_corrigido)
        if len(num) == 14 and validar_digitos_cnpj(num):
            cnpjs_validos.add(num)

    # 2. Varredura por blocos contínuos no texto limpo
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
    """Lê o arquivo anexado utilizando OCR padrão e aprimorado por contraste."""
    extensao = uploaded_file.name.split('.')[-1].lower()
    texto_extraido = ""

    try:
        if extensao in ['jpg', 'jpeg', 'png']:
            imagem = Image.open(uploaded_file)
            
            # 1. Leitura padrão
            texto_extraido += pytesseract.image_to_string(imagem, lang='por') + "\n"
            
            # 2. Leitura com alto contraste para fotos de papel
            img_cinza = imagem.convert('L')
            enhancer = ImageEnhance.Contrast(img_cinza)
            img_contraste = enhancer.enhance(2.5)
            texto_extraido += pytesseract.image_to_string(img_contraste, lang='por') + "\n"
            
            # 3. Leitura PSM 6 (tabelas/blocos)
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

    # 2. RESULTADOS DA VALIDAÇÃO NA RECEITA FEDERAL
    if tipo_documento != "Documento Genérico / Não Identificado":
        st.divider()
        st.subheader("🔍 Validação na Receita Federal")

        if not cnpjs_encontrados:
            st.warning("⚠️ Nenhum CNPJ válido foi encontrado no arquivo anexado.")
        else:
            for cnpj in cnpjs_encontrados:
                cnpj_formatado = formatar_cnpj(cnpj)
                
                # Se o CNPJ estiver associado diretamente ao termo CONSELHO DE ESCOLA no texto extraído, pula sem consultar
                if "CONSELHO DE ESCOLA" in conteudo_texto.upper() and (cnpj_formatado in conteudo_texto or cnpj in conteudo_texto):
                    continue

                dados = consultar_receita_federal(cnpj)

                razao_social_oficial = dados.get("razao_social", "") if isinstance(dados, dict) else ""

                # FILTRO SILENCIOSO: Se for "Conselho de Escola", ignora e não exibe na tela
                if "CONSELHO DE ESCOLA" in razao_social_oficial.upper():
                    continue

                if "erro" in dados:
                    # Oculta mensagens de erro 500 caso seja instabilidade referente a entidades públicas/conselhos
                    if "500" in str(dados.get("erro", "")):
                        continue
                    with st.expander(f"CNPJ: {cnpj_formatado}", expanded=True):
                        st.error(f"❌ **CNPJ {cnpj_formatado}:** {dados['erro']}")
                else:
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
