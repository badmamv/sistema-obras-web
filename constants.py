import string
import random
import hashlib
import re
import json
import os
import sys
import datetime
import base64
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="google.cloud.firestore_v1")

try:
    import firebase_admin
    from firebase_admin import credentials, firestore, storage
except ImportError:
    firebase_admin = None

CONFIG_FILE = "config.json"
CONFIG_OMS_FILE = "config_om.json"
MASTER_CONFIG_FILE = "master_config.json"
USUARIOS_FILE = "data_usuarios_cadastrados.json"
ENTRADA_FILE = "data_entrada.json"
MASTER_PASSWORD_ENV = "MASTER_PASSWORD"
SINAPI_INSUMOS_FILE = "sinapi_insumos_sp_202603.json"
SINAPI_COMPOSICOES_FILE = "sinapi_custo_ref_composicoes_sp_202603.json"

class SheetColumns:
    ENTRADA_ID = 0
    ENTRADA_DATA = 1
    ENTRADA_STATUS = 2
    ENTRADA_SOLICITANTE = 3
    ENTRADA_LOCAL = 4
    ENTRADA_TIPO = 5
    ENTRADA_DESCRICAO = 6
    ENTRADA_URGENCIA = 7
    ENTRADA_OM = 8
    ENTRADA_PRIORIDADE = 9
    ENTRADA_FOTOURL = 10
    ENTRADA_PARECER_PO = 11
    ENTRADA_REGISTRO = 12
    USUARIOS_OM = 0
    USUARIOS_NOME = 1
    USUARIOS_IDENTIDADE = 2
    USUARIOS_FUNCAO = 3
    USUARIOS_SENHA = 4
    USUARIOS_STATUS = 5
    USUARIOS_HIDDEN_IDS = 6
    APROV_ID = 0
    APROV_DATA = 1
    APROV_STATUS = 2
    APROV_SOLICITANTE = 3
    APROV_LOCAL = 4
    APROV_TIPO = 5
    APROV_DESCRICAO = 6
    APROV_URGENCIA = 7
    APROV_OM = 8
    APROV_PRIORIDADE = 9
    APROV_FOTOURL = 10
    APROV_PARECER_PO = 11
    APROV_REGISTRO = 12

HEADER_DEMANDA = [
    "ID", "Data", "Status", "Solicitante", "Local", "Tipo", "Descrição",
    "Urgência", "OM", "Prioridade", "FotoURL", "ParecerPO", "Registro",
]

def descricao_original(descricao):
    if not descricao:
        return ""
    texto = str(descricao)
    texto = re.sub(
        r'\[(APROVADO|RETORNO|Aprovado|Devolvido|Mat|PO EXECUTA|PO NAO EXECUTA)[^\]]*\]:?[^\n]*',
        '', texto, flags=re.IGNORECASE)
    texto = re.sub(
        r'(Aprovado|Devolvido|Encaminhado) por [^\n\r]*', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'Parecer da Seção de Serviços Gerais[^\n]*', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\n\s*\n+', '\n', texto).strip()
    return texto

def load_config_oms():
    if os.path.exists(CONFIG_OMS_FILE):
        try:
            with open(CONFIG_OMS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Erro ao carregar config_om.json: {e}")
            return {}
    else:
        print(f"Arquivo {CONFIG_OMS_FILE} nao encontrado. Usando configuracao padrao.")
        return {}

CONFIG_OMS = load_config_oms()

OM_ALIASES = {
    "Base Adm Amv": "Base Administrativa",
    "Cia C Bda Inf Amv": "Cia C"
}

ROLE_ALIASES = {
    "Encarregado de Material": "Enc Mat",
    "S4": "Fisc Adm OM/S4",
    "Seção de Infraestrutura": "Fisc Adm Base"
}

GLOBAL_UNIQUE_ROLES = ["Fisc Adm Base", "Chefe da Seção de Infraestrutura", "Seção de Serviços Gerais"]

APROVACOES_BLOCOS = {
    "Aprovados_Fisc_Adm": "Fiscalização Administrativa",
    "Aprovados_Infraestrutura": "Seção de Infraestrutura",
    "Aprovados_Servicos_Gerais": "Seção de Serviços Gerais",
}

STATUS_ANALISE_SERVICOS_GERAIS = "Aguardando Análise Serviços Gerais"
STATUS_ANALISE_INFRAESTRUTURA = "Em análise pela Seção de Infraestrutura"
STATUS_RECEBIDO_INFRAESTRUTURA = "Recebido pela Seção de Infraestrutura"

TAG_PO_EXECUTA = "PO EXECUTA"
TAG_PO_NAO_EXECUTA = "PO NÃO EXECUTA"
FUNCAO_SECAO_SERVICOS_GERAIS = "Seção de Serviços Gerais"
FUNCAO_FISC_ADM_BASE = "Fisc Adm Base"

STATUS_EM_EXECUCAO_PO = "Em execução pelo PO"
STATUS_CONCLUIDO_PO = "Serviço Concluído - PO"
STATUS_CONCLUIDO_INFRA = "Serviço Concluído - Infraestrutura"

ROLES_COM_APROVACOES = frozenset({FUNCAO_FISC_ADM_BASE, FUNCAO_SECAO_SERVICOS_GERAIS, "Chefe da Seção de Infraestrutura", "Administrador da OM"})

ACOES_MARGEM = 2
BTN_ACAO_GAP_H = 4
BTN_ACAO_GAP_V = 3
ACOES_W_FISC = 230
ACOES_W_STD = 170
ACOES_W_SG = 130
ACOES_H_STD = 32
ACOES_H_FISC = 32
ACOES_H_SG = 32
ACOES_H_COMPACTO = 32
ACOES_W_COMPACTO = 165

ROLES_PODEM_CRIAR_SOLICITACAO = frozenset({"Enc Mat", "Encarregado de Material", "Aj G", "Almox"})

def status_para_bloco_aprovacao(table_name):
    if table_name == "Aprovados_Servicos_Gerais":
        return STATUS_ANALISE_SERVICOS_GERAIS
    if table_name == "Aprovados_Infraestrutura":
        return STATUS_ANALISE_INFRAESTRUTURA
    return f"Aprovado - {table_name}"

def status_alvos_bloco_aprovacao(table_name):
    atual = status_para_bloco_aprovacao(table_name)
    legado = f"Aprovado - {table_name}"
    status_list = [atual] if legado == atual else [atual, legado]
    if table_name == "Aprovados_Fisc_Adm":
        status_list.append("Analise concluida pelo PO")
        status_list.append(STATUS_EM_EXECUCAO_PO)
        status_list.append(STATUS_ANALISE_SERVICOS_GERAIS)
        status_list.append(STATUS_ANALISE_INFRAESTRUTURA)
        status_list.append(STATUS_RECEBIDO_INFRAESTRUTURA)
        return status_list
    if table_name == "Aprovados_Infraestrutura":
        status_list.append(STATUS_RECEBIDO_INFRAESTRUTURA)
    if table_name == "Aprovados_Servicos_Gerais":
        status_list.append(STATUS_EM_EXECUCAO_PO)
    return [s for s in status_list
            if s not in (STATUS_ANALISE_INFRAESTRUTURA, STATUS_ANALISE_SERVICOS_GERAIS)]

def extrair_parecer_po(parecer_po=None, descricao=None):
    if parecer_po in (TAG_PO_EXECUTA, TAG_PO_NAO_EXECUTA):
        return parecer_po
    if not descricao:
        return None
    texto = str(descricao)
    if f"[{TAG_PO_NAO_EXECUTA}]" in texto or TAG_PO_NAO_EXECUTA in texto:
        return TAG_PO_NAO_EXECUTA
    if f"[{TAG_PO_EXECUTA}]" in texto or TAG_PO_EXECUTA in texto:
        return TAG_PO_EXECUTA
    return None

def linha_demanda_de_doc(d):
    return [
        d.get("ID", ""),
        d.get("Data", ""),
        d.get("Status", ""),
        d.get("Solicitante", ""),
        d.get("Local", ""),
        d.get("Tipo", ""),
        descricao_original(d.get("Descrição", d.get("Descricao", ""))),
        d.get("Urgência", d.get("Urgencia", "")),
        d.get("OM", ""),
        d.get("Prioridade", ""),
        d.get("FotoURL", ""),
        d.get("ParecerPO", ""),
        d.get("Registro", ""),
    ]

def resolve_role(role_name):
    return ROLE_ALIASES.get(role_name, role_name)

def resolve_om(om_name):
    if om_name in CONFIG_OMS:
        return om_name
    return OM_ALIASES.get(om_name, om_name)

def gerar_hash_senha(senha):
    if not senha:
        return ""
    salt = os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, 600000)
    import base64
    return base64.b64encode(salt).decode('ascii') + '$' + base64.b64encode(hash_bytes).decode('ascii')

def verificar_senha(senha, hash_armazenado):
    if not senha or not hash_armazenado:
        return False
    if len(hash_armazenado) == 64 and all(c in '0123456789abcdef' for c in hash_armazenado):
        return hashlib.sha256(senha.encode('utf-8')).hexdigest() == hash_armazenado
    if '$' in hash_armazenado:
        parts = hash_armazenado.split('$')
        if len(parts) == 2:
            import base64
            try:
                salt = base64.b64decode(parts[0])
                hash_esperado = base64.b64decode(parts[1])
                hash_calculado = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, 600000)
                return hash_calculado == hash_esperado
            except Exception:
                return False
    return senha == hash_armazenado
