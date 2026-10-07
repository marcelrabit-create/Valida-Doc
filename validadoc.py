import streamlit as st
import re
import requests
import pandas as pd
import pdfplumber
from PIL import Image, ImageEnhance, ImageOps
import pytesseract
import time
import cv2
import numpy as np

# Configuração da página
st.set_page_config(page_title="Validador de Documentos", page_icon="📋", layout="wide")

# Inicialização do estado da sessão
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "validado" not in st.session_state:
    st.session_state.validado = False

if "texto_processado" not in st.session_state:
    st.session_state.texto_processado = ""

if "tipo_doc" not in st.session_state:
    st.session_state.tipo_doc = ""

# --- OCULTAR ELEMENTOS PADRÃO DO STREAMLIT ---
estilo_css = """
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .stAppHeader {display: none;}
    </style>
"""
st.markdown(estilo_css, unsafe_allow_html=True)

st.title("📋 Validador de Documentos")
st.write("Faça upload do documento para identificar o tipo e validar os CNPJs ou blocos de consolidação.")

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

# --- CORREÇÃO DE ERROS TÍPICOS DE OCR EM NÚMEROS ---

def corrigir_substituicoes_ocr(string_cand: str) -> str:
    mapeamento = {
        'O': '0', 'o': '0', 'D': '0', 'Q': '0',
        'I': '1', 'l': '1', 'L': '1', '|': '1', '!': '1',
        'Z': '2', 'z': '2',
        'S': '5', 's': '5', '$': '5',
        'G': '6', 'b': '6',
        'B': '8'
    }
    return "".join([mapeamento.get(char, char) for char in string_cand])

# --- CLASSIFICAÇÃO DE DOCUMENTO ---

def identificar_tipo_documento(texto: str) -> str:
    texto_upper = texto.upper()
    if any(k in texto_upper for k in ["CONSOLIDACAO", "CONSOLIDAÇÃO", "PESQUISAS DE PRECOS", "PESQUISAS DE PREÇOS", "BLOCO I", "UEX", "PDDE"]):
        return "Consolidação de Pesquisas de Preços"
    elif any(k in texto_upper for k in ["NOTA FISCAL DE SERVICOS", "NOTA FISCAL DE SERVIÇOS", "NFS-E", "NFSE", "ISSQN"]):
        return "Nota Fiscal de Serviços"
    elif any(k in texto_upper for k in ["DANFE", "DOCUMENTO AUXILIAR DA NOTA FISCAL", "NFE", "NF-E", "CHAVE DE ACESSO"]):
        return "Nota Fiscal de Compra de Materiais"
    else:
        return "Documento Genérico / Não Identificado"

# --- CONSULTA À RECEITA FEDERAL ---

@st.cache_data(ttl=3600)
def consultar_receita_federal(cnpj: str) -> dict:
    cnpj_limpo = re.sub(r'\D', '', str(cnpj))
    endpoints = [
        f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
        f"https://minhareceita.org/{cnpj_limpo}",
        f"https://receitaws.com.br/v1/cnpj/{cnpj_limpo}"
    ]

    for url in endpoints:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                dados = response.json()
                if "minhareceita.org" in url or "brasilapi" in url:
                    return {
                        "razao_social": dados.get("razao_social") or dados.get("nome", "N/A"),
                        "nome_fantasia": dados.get("nome_fantasia") or dados.get("fantasia", "Não informado"),
                        "descricao_situacao_cadastral": dados.get("descricao_situacao_cadastral") or dados.get("situacao", "DESCONHECIDA"),
                        "data_situacao": dados.get("data_situacao_cadastral") or dados.get("data_situacao", "Não informada"),
                        "uf": dados.get("uf", ""),
                        "municipio": dados.get("municipio", ""),
                        "cnae_fiscal_descricao": dados.get("cnae_fiscal_descricao") or (dados.get("atividade_principal", [{}]) or [{}])[0].get("text", "N/A")
                    }
                elif dados.get("status") != "ERROR":
                    return {
                        "razao_social": dados.get("nome", "N/A"),
                        "nome_fantasia": dados.get("fantasia", "Não informado"),
                        "descricao_situacao_cadastral": dados.get("situacao", "DESCONHECIDA"),
                        "data_situacao": dados.get("data_situacao", "Não informada"),
                        "uf": dados.get("uf", ""),
                        "municipio": dados.get("municipio", ""),
                        "cnae_fiscal_descricao": (dados.get("atividade_principal", [{}]) or [{}])[0].get("text", "N/A")
                    }
        except Exception:
            pass
    return {"erro": "API de consulta temporariamente indisponível para este CNPJ."}

def formatar_cnpj(cnpj: str) -> str:
    c = re.sub(r'\D', '', str(cnpj))
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"

# --- EXTRAÇÃO FLEXÍVEL DE CNPJ DA UNIDADE ESCOLAR ---

def extrair_cnpj_unidade_escolar(texto: str) -> str:
    texto_corrigido = corrigir_substituicoes_ocr(texto)
    
    # Procura por padrões como "02 - CNPJ" ou "CNPJ:" no início do documento
    match = re.search(r'(?:02|0Z|O2|2)\s*[\-\:]?\s*CNPJ[^\d]*(\d[\d\.\-/]{13,18}\d)', texto_corrigido, re.IGNORECASE)
    if match:
        c_limpo = re.sub(r'\D', '', match.group(1))
        if len(c_limpo) == 14 and validar_digitos_cnpj(c_limpo):
            return c_limpo

    # Fallback: Varre todos os CNPJs válidos e pega o primeiro (Geralmente a UEx no Bloco I)
    cnpjs = extrair_cnpjs_de_texto(texto)
    if cnpjs:
        return cnpjs[0]
        
    return ""

# --- EXTRAÇÃO GERAL DE CNPJS DA PÁGINA ---

def extrair_cnpjs_de_texto(texto: str) -> list:
    cnpjs_validos = []
    
    # Tenta extrair com padrões com e sem pontuação
    padrao_cnpj = r'\b[0-9OoDDIlLZSsGGB]{2}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[/\s1lI|]?[0-9OoDDIlLZSsGGB]{4}[-\s]?[0-9OoDDIlLZSsGGB]{2}\b'
    for c in re.findall(padrao_cnpj, texto):
        c_corrigido = corrigir_substituicoes_ocr(c)
        num = re.sub(r'\D', '', c_corrigido)
        if len(num) == 14 and validar_digitos_cnpj(num) and num not in cnpjs_validos:
            cnpjs_validos.append(num)

    # Varredura secundária por sequências numéricas de 14 dígitos
    texto_limpo = corrigir_substituicoes_ocr(texto)
    apenas_numeros = re.sub(r'\D', ' ', texto_limpo)
    for bloco in apenas_numeros.split():
        if len(bloco) >= 14:
            for i in range(len(bloco) - 13):
                cand = bloco[i:i+14]
                if len(cand) == 14 and validar_digitos_cnpj(cand) and cand not in cnpjs_validos:
                    cnpjs_validos.append(cand)

    return cnpjs_validos

# --- PROCESSAMENTO DE IMAGEM OCR COMPLETO ---

def otimizar_imagem_para_ocr(imagem_pil: Image.Image) -> Image.Image:
    imagem_pil = ImageOps.exif_transpose(imagem_pil)
    img_np = np.array(imagem_pil.convert('L'))
    
    # Equalização Adaptativa de Histograma (CLAHE) para balancear a sombra da margem esquerda
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    img_equalizada = clahe.apply(img_np)
    
    # Suavização suave para reduzir ruído de escaneamento
    img_blur = cv2.GaussianBlur(img_equalizada, (3, 3), 0)
    
    return Image.fromarray(img_blur)

def ler_arquivo(uploaded_file) -> str:
    extensao = uploaded_file.name.split('.')[-1].lower()
    texto_completo = ""

    try:
        if extensao in ['jpg', 'jpeg', 'png']:
            imagem_original = Image.open(uploaded_file)
            imagem_otimizada = otimizar_imagem_para_ocr(imagem_original)
            
            # Passagem 1: Leitura Automática Geral (PSM 3)
            txt_psm3 = pytesseract.image_to_string(imagem_otimizada, lang='por', config='--psm 3')
            
            # Passagem 2: Leitura Sem Estrutura Rígida (PSM 11) - Ideal para tabelas com sombras
            txt_psm11 = pytesseract.image_to_string(imagem_otimizada, lang='por', config='--psm 11')
            
            texto_completo = txt_psm3 + "\n" + txt_psm11

        elif extensao == 'pdf':
            with pdfplumber.open(uploaded_file) as pdf:
                for pagina in pdf.pages:
                    t = pagina.extract_text()
                    if t:
                        texto_completo += t + "\n"
            
            if not texto_completo.strip():
                uploaded_file.seek(0)
                with pdfplumber.open(uploaded_file) as pdf:
                    for pagina in pdf.pages:
                        img = pagina.to_image(resolution=300).original
                        img_otim = otimizar_imagem_para_ocr(img)
                        texto_completo += pytesseract.image_to_string(img_otim, lang='por', config='--psm 3') + "\n"
                        texto_completo += pytesseract.image_to_string(img_otim, lang='por', config='--psm 11') + "\n"

        elif extensao == 'txt':
            texto_completo = uploaded_file.read().decode('utf-8', errors='ignore')

        elif extensao in ['xls', 'xlsm', 'xlsx']:
            df_dict = pd.read_excel(uploaded_file, sheet_name=None)
            for _, aba in df_dict.items():
                texto_completo += f" {aba.to_string()} "

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")

    return texto_completo

# --- VALIDAÇÃO DO BLOCO IV ---

def validar_consolidacao_precos(texto: str) -> list:
    erros = []
    texto_upper = texto.upper()

    # Verifica se existem indicativos de apuração de proposta (valores, itens ou indicações de menor valor)
    tem_itens = any(k in texto_upper for k in [
        "MENOR VALOR", "ITENS DE MENOR", "PROPONENTE (A)", "PROPONENTE (B)", 
        "PROPONENTE (C)", "APURAÇÃO", "APURACAO", "VENCEDOR"
    ]) or re.search(r'\b(ITEM|R\$|\d+,\d{2})\b', texto_upper)

    if not tem_itens:
        erros.append("Faltam itens de menor valor no Bloco IV.")

    return erros

# --- FLUXO DA INTERFACE ---

if not st.session_state.validado:
    arquivo = st.file_uploader(
        "Anexe o documento (PDF, JPG, JPEG, PNG, TXT, XLS, XLSM)",
        type=["pdf", "jpg", "jpeg", "png", "txt", "xls", "xlsm", "xlsx"],
        key=f"uploader_{st.session_state.uploader_key}"
    )

    if arquivo is not None:
        with st.spinner("Lendo e processando o documento com OCR adaptativo..."):
            st.session_state.texto_processado = ler_arquivo(arquivo)
            st.session_state.tipo_doc = identificar_tipo_documento(st.session_state.texto_processado)
            st.session_state.validado = True
            st.rerun()

if st.session_state.validado:
    st.divider()

    st.subheader("📄 Tipo de Documento")
    if st.session_state.tipo_doc != "Documento Genérico / Não Identificado":
        st.success(f"**{st.session_state.tipo_doc}**")
    else:
        st.info(f"**{st.session_state.tipo_doc}**")

    # 1º: UNIDADE ESCOLAR (BLOCO I)
    cnpj_uex = ""
    if st.session_state.tipo_doc == "Consolidação de Pesquisas de Preços":
        st.divider()
        st.subheader("🏫 Unidade Escolar")
        
        cnpj_uex = extrair_cnpj_unidade_escolar(st.session_state.texto_processado)
        if cnpj_uex:
            dados_uex = consultar_receita_federal(cnpj_uex)
            razao_social_uex = dados_uex.get("razao_social", "Não encontrada na Receita Federal")
            cnpj_formatado_uex = formatar_cnpj(cnpj_uex)
        else:
            razao_social_uex = "Não identificada"
            cnpj_formatado_uex = "Não encontrado"

        st.write(f"**Razão Social:** {razao_social_uex}")
        st.write(f"**CNPJ:** {cnpj_formatado_uex}")

    # 2º: PROPONENTES / FORNECEDORES (BLOCO II)
    if st.session_state.tipo_doc != "Documento Genérico / Não Identificado":
        st.divider()
        st.subheader("🔍 Validação na Receita Federal")

        cnpjs_encontrados = extrair_cnpjs_de_texto(st.session_state.texto_processado)
        cnpj_uex_limpo = re.sub(r'\D', '', str(cnpj_uex)) if cnpj_uex else ""

        # Oculta o CNPJ do FNDE ("06.697.670/0001-95") e o da própria Unidade Escolar
        cnpjs_para_exibir = []
        for c in cnpjs_encontrados:
            c_limpo = re.sub(r'\D', '', c)
            if c_limpo != "06697670000195" and c_limpo != cnpj_uex_limpo:
                if c_limpo not in [re.sub(r'\D', '', x) for x in cnpjs_para_exibir]:
                    cnpjs_para_exibir.append(c)

        if not cnpjs_para_exibir:
            st.warning("⚠ Nenhum CNPJ de fornecedor/emitente válido foi encontrado no arquivo anexado.")
        else:
            for cnpj in cnpjs_para_exibir:
                dados = consultar_receita_federal(cnpj)
                cnpj_formatado = formatar_cnpj(cnpj)

                if isinstance(dados, dict) and "erro" in dados:
                    with st.expander(f"CNPJ: {cnpj_formatado}", expanded=True):
                        st.error(f"❌ **CNPJ {cnpj_formatado}:** {dados['erro']}")
                else:
                    razao_social_oficial = dados.get("razao_social", "N/A")
                    situacao = dados.get("descricao_situacao_cadastral", "DESCONHECIDA")
                    data_situacao = dados.get("data_situacao", "Não informada")
                    nome_fantasia = dados.get("nome_fantasia") or "Não informado"
                    uf = dados.get("uf", "")
                    municipio = dados.get("municipio", "")

                    with st.expander(f"CNPJ: {cnpj_formatado}", expanded=True):
                        if situacao.upper() == "ATIVA":
                            st.success(f"**Situação Cadastral:** {situacao}")
                        else:
                            st.warning(f"**Situação Cadastral:** {situacao} (Data da alteração: {data_situacao})")

                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Razão Social Oficial:** {razao_social_oficial}")
                            st.write(f"**Nome Fantasia:** {nome_fantasia}")
                        with col2:
                            st.write(f"**Cidade/UF:** {municipio} - {uf}")
                            st.write(f"**Atividade Principal:** {dados.get('cnae_fiscal_descricao', 'N/A')}")

    # 3º: VALIDAÇÃO DOS BLOCOS DA CONSOLIDAÇÃO (BLOCOS III E IV)
    if st.session_state.tipo_doc == "Consolidação de Pesquisas de Preços":
        st.divider()
        st.subheader("🔍 Validação dos Blocos (Consolidação de Preços)")
        
        erros_consolidacao = validar_consolidacao_precos(st.session_state.texto_processado)
        
        if erros_consolidacao:
            for erro in erros_consolidacao:
                st.error(f"❌ {erro}")
        else:
            st.success("✅ Nenhum erro encontrado nos blocos III e IV da consolidação.")

    st.divider()
    if st.button("⬅ Voltar (Nova Validação)", use_container_width=True):
        st.session_state.validado = False
        st.session_state.texto_processado = ""
        st.session_state.tipo_doc = ""
        st.session_state.uploader_key += 1
        st.rerun()
