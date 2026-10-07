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

# --- FUNÇÃO DE CLASSIFICAÇÃO DO DOCUMENTO (FLEXÍVEL) ---

def identificar_tipo_documento(texto: str) -> str:
    """Classifica o documento com base em palavras-chave abrangentes encontradas no texto."""
    texto_upper = texto.upper()

    if (
        "CONSOLIDACAO" in texto_upper or "CONSOLIDAÇÃO" in texto_upper or 
        "PESQUISAS DE PRECOS" in texto_upper or "PESQUISAS DE PREÇOS" in texto_upper or 
        "BLOCO I" in texto_upper or "UEX" in texto_upper or 
        "PROGRAMA DINHEIRO DIRETO NA ESCOLA" in texto_upper or "PDDE" in texto_upper
    ):
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

# --- CONSULTA À RECEITA FEDERAL COM MÚLTIPLAS APIS DE CONTINGÊNCIA ---

@st.cache_data(ttl=3600)
def consultar_receita_federal(cnpj: str) -> dict:
    """Consulta múltiplas APIs públicas de CNPJ em cascata para evitar falhas de instabilidade."""
    cnpj_limpo = re.sub(r'\D', '', str(cnpj))
    
    endpoints = [
        f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
        f"https://minhareceita.org/{cnpj_limpo}",
        f"https://receitaws.com.br/v1/cnpj/{cnpj_limpo}"
    ]

    for tentativa in range(2):
        for url in endpoints:
            try:
                response = requests.get(url, timeout=7)
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
                elif response.status_code == 404:
                    return {"erro": "CNPJ não encontrado na base da Receita Federal."}
            except (requests.RequestException, requests.Timeout):
                pass
        
        time.sleep(1)

    return {"erro": "A API pública de consulta está temporariamente indisponível para este CNPJ de filial. Tente novamente em instantes."}

def formatar_cnpj(cnpj: str) -> str:
    c = re.sub(r'\D', '', str(cnpj))
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"

# --- EXTRAÇÃO ESTRITA DO CNPJ DO BLOCO I (UNIDADE ESCOLAR) ---

def extrair_cnpj_unidade_escolar(texto: str) -> str:
    """Extrai o CNPJ estritamente contido no Bloco I (Identificação da Unidade Executora Própria)."""
    texto_upper = texto.upper()
    
    bloco_i_texto = texto_upper
    if "BLOCO II" in texto_upper:
        bloco_i_texto = texto_upper.split("BLOCO II")[0]
    
    match_rotulo = re.search(r'(?:0?2\s*[-–]?\s*CNPJ|CNPJ)[:\s]*([0-9\.\-/]{14,18})', bloco_i_texto)
    if match_rotulo:
        c_limpo = re.sub(r'\D', '', match_rotulo.group(1))
        if len(c_limpo) == 14 and validar_digitos_cnpj(c_limpo):
            return c_limpo

    padrao_cnpj = r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b'
    cnpjs = re.findall(padrao_cnpj, bloco_i_texto)
    
    for c in cnpjs:
        c_limpo = re.sub(r'\D', '', c)
        if len(c_limpo) == 14 and validar_digitos_cnpj(c_limpo):
            return c_limpo
            
    return ""

# --- PRÉ-PROCESSAMENTO E TRATAMENTO DE TEXTO OCR ---

def otimizar_imagem_para_ocr(imagem_pil: Image.Image) -> Image.Image:
    """Redimensiona imagens muito grandes e melhora o contraste para acelerar o OCR."""
    imagem_pil = ImageOps.exif_transpose(imagem_pil)
    
    # Redimenciona se a largura ou altura ultrapassar 2000px
    max_dim = 2000
    if max(imagem_pil.size) > max_dim:
        imagem_pil.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        
    img_cinza = imagem_pil.convert('L')
    enhancer = ImageEnhance.Contrast(img_cinza)
    return enhancer.enhance(2.0)

def corrigir_substituicoes_ocr(string_cand: str) -> str:
    mapeamento = {
        'O': '0', 'o': '0', 'D': '0',
        'I': '1', 'l': '1', 'L': '1', '|': '1',
        'Z': '2',
        'S': '5', 's': '5',
        'G': '6',
        'B': '8'
    }
    return "".join([mapeamento.get(char, char) for char in string_cand])

def extrair_cnpjs_de_texto(texto: str) -> list:
    cnpjs_validos = set()

    padrao_cnpj = r'\b[0-9OoDDIlLZSsGGB]{2}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[\.\s]?[0-9OoDDIlLZSsGGB]{3}[/\s1lI|]?[0-9OoDDIlLZSsGGB]{4}[-\s]?[0-9OoDDIlLZSsGGB]{2}\b'
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

def validar_consolidacao_precos(texto: str) -> list:
    """Verifica regras de preenchimento dos Blocos III e IV para Consolidação de Preços."""
    erros = []
    texto_upper = texto.upper()

    if "BLOCO IV" not in texto_upper and "APURAÇÃO" not in texto_upper and "APURACAO" not in texto_upper:
        erros.append("Bloco IV (Apuração das Propostas) não identificado no documento.")
        return erros

    tem_proponente_vencedor = False
    if re.search(r'PROPONENTE\s*\([ABC]\)\s*[\:\-\s]*[1-9]', texto_upper) or "14 - ITENS DE MENOR VALOR" in texto_upper or "PROPONENTE (A) 1" in texto_upper or "PROPONENTE (A)" in texto_upper:
        tem_proponente_vencedor = True

    if not tem_proponente_vencedor:
        if not re.search(r'(?:PROPONENTE|ITEM)\s*[A-C1-9]', texto_upper):
            erros.append("Faltam itens de menor valor no Bloco IV.")

    return erros

# --- FUNÇÃO DE LEITURA OTIMIZADA ---

def ler_arquivo(uploaded_file) -> str:
    extensao = uploaded_file.name.split('.')[-1].lower()
    texto_extraido = ""

    try:
        if extensao in ['jpg', 'jpeg', 'png']:
            imagem_original = Image.open(uploaded_file)
            imagem_otimizada = otimizar_imagem_para_ocr(imagem_original)
            
            # 1. Tenta a leitura direta na orientação ajustada pelo EXIF (PSM 6 é ideal para tabelas/documentos)
            texto_direto = pytesseract.image_to_string(imagem_otimizada, lang='por', config='--psm 6')
            cnpjs = extrair_cnpjs_de_texto(texto_direto)

            # Critério de saída rápida (Early Exit): se já encontrou CNPJ válido ou palavras de consolidação, encerra
            if len(cnpjs) >= 2 or "CONSOLIDAÇÃO" in texto_direto.upper() or "PDDE" in texto_direto.upper():
                return texto_direto

            texto_extraido += texto_direto + "\n"

            # 2. Se a leitura direta não foi conclusiva, testa os outros ângulos (90°, 180°, 270°)
            for angulo in [90, 180, 270]:
                img_rot = imagem_otimizada.rotate(angulo, expand=True)
                t = pytesseract.image_to_string(img_rot, lang='por', config='--psm 6')
                texto_extraido += t + "\n"
                
                # Se encontrar informações suficientes em outro ângulo, encerra o loop de rotação
                if len(extrair_cnpjs_de_texto(t)) >= 2:
                    break

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
                        img_otim = otimizar_imagem_para_ocr(img)
                        texto_extraido += pytesseract.image_to_string(img_otim, lang='por', config='--psm 6') + "\n"

        elif extensao == 'txt':
            texto_extraido = uploaded_file.read().decode('utf-8', errors='ignore')

        elif extensao in ['xls', 'xlsm', 'xlsx']:
            df_dict = pd.read_excel(uploaded_file, sheet_name=None)
            for nome_aba, aba in df_dict.items():
                texto_extraido += f" {aba.to_string()} "

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")

    return texto_extraido

# --- INTERFACE E FLUXO PRINCIPAL ---

if not st.session_state.validado:
    arquivo = st.file_uploader(
        "Anexe o documento (PDF, JPG, JPEG, PNG, TXT, XLS, XLSM)",
        type=["pdf", "jpg", "jpeg", "png", "txt", "xls", "xlsm", "xlsx"],
        key=f"uploader_{st.session_state.uploader_key}"
    )

    if arquivo is not None:
        with st.spinner("Lendo e processando o documento..."):
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

    # 1º: IDENTIFICAÇÃO DA UNIDADE ESCOLAR (APENAS DO BLOCO I)
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

    # 2º: VALIDAÇÃO NA RECEITA FEDERAL (DOS FORNECEDORES/PROPONENTES)
    if st.session_state.tipo_doc != "Documento Genérico / Não Identificado":
        st.divider()
        st.subheader("🔍 Validação na Receita Federal")

        cnpjs_encontrados = extrair_cnpjs_de_texto(st.session_state.texto_processado)
        
        cnpj_uex_limpo = re.sub(r'\D', '', str(cnpj_uex)) if cnpj_uex else ""

        cnpjs_para_exibir = [
            c for c in cnpjs_encontrados 
            if re.sub(r'\D', '', c) != "06697670000195" and (not cnpj_uex_limpo or re.sub(r'\D', '', c) != cnpj_uex_limpo)
        ]

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

                    if "CONSELHO DE ESCOLA" in razao_social_oficial.upper():
                        continue

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

    # 3º: VALIDAÇÃO DOS BLOCOS (SE FOR CONSOLIDAÇÃO DE PREÇOS)
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
