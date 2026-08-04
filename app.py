import streamlit as st
import json
import os
import re
import base64
import datetime
import time
import io
from PIL import Image

from constants import (
    CONFIG_OMS, SheetColumns, HEADER_DEMANDA, resolve_om, resolve_role,
    GLOBAL_UNIQUE_ROLES, ROLES_PODEM_CRIAR_SOLICITACAO, ROLES_COM_APROVACOES,
    FUNCAO_SECAO_SERVICOS_GERAIS, FUNCAO_FISC_ADM_BASE, APROVACOES_BLOCOS,
    STATUS_ANALISE_SERVICOS_GERAIS, STATUS_ANALISE_INFRAESTRUTURA,
    STATUS_RECEBIDO_INFRAESTRUTURA, TAG_PO_EXECUTA, TAG_PO_NAO_EXECUTA,
    STATUS_EM_EXECUCAO_PO, STATUS_CONCLUIDO_PO, STATUS_CONCLUIDO_INFRA,
    status_para_bloco_aprovacao, status_alvos_bloco_aprovacao,
    extrair_parecer_po, descricao_original, verificar_senha,
    SINAPI_INSUMOS_FILE, SINAPI_COMPOSICOES_FILE,
)
from supabase_manager import SupabaseManager

SUPABASE_CONFIG_FILE = "supabase_config.json"

TIPOS_ORIGINAIS = ["Manutenção", "Reparo", "Obra"]
URGENCIAS_ORIGINAIS = ["Baixa", "Média", "Alta"]


def load_supabase_config():
    try:
        if hasattr(st, 'secrets'):
            url = ""
            key = ""
            skey = ""
            if 'supabase' in st.secrets:
                url = st.secrets.supabase.get("supabase_url", "")
                key = st.secrets.supabase.get("supabase_key", "")
                skey = st.secrets.supabase.get("supabase_service_key", "")
            elif 'supabase_url' in st.secrets:
                url = st.secrets.get("supabase_url", "")
                key = st.secrets.get("supabase_key", "")
                skey = st.secrets.get("supabase_service_key", "")
            if url and key:
                return {
                    "use_supabase": True,
                    "supabase_url": url,
                    "supabase_key": skey if skey else key,
                    "supabase_service_key": skey if skey else key,
                    "poll_interval_ms": 3000,
                }
    except Exception:
        pass
    if not os.path.exists(SUPABASE_CONFIG_FILE):
        return {"use_supabase": False}
    try:
        with open(SUPABASE_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"use_supabase": False}


def create_manager():
    config = load_supabase_config()
    if not config.get("use_supabase", False):
        return None
    try:
        mgr = SupabaseManager(
            supabase_url=config.get("supabase_url", ""),
            supabase_key=config.get("supabase_service_key", config.get("supabase_key", "")),
            poll_interval_ms=config.get("poll_interval_ms", 3000),
        )
        success, msg = mgr.connect()
        if success:
            return mgr
        else:
            st.error(f"Erro Supabase: {msg}")
    except Exception as e:
        st.error(f"Erro ao criar SupabaseManager: {e}")
    return None


def get_manager():
    if "manager" not in st.session_state:
        st.session_state.manager = create_manager()
    return st.session_state.manager


def init_session_state():
    defaults = {
        "logged_in": False,
        "user_data": None,
        "page": "solicitacoes",
        "editing_id": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def generate_id():
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:14]


def compress_and_encode_image(uploaded_file, max_size=(1024, 1024), quality=70):
    try:
        img = Image.open(uploaded_file)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        data = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/jpeg;base64,{data}"
    except Exception:
        return None


def apply_status_color(status_text):
    if not status_text:
        return ""
    s = str(status_text).lower()
    if "conclu" in s:
        return "background-color: #27ae60; color: white;"
    elif "aprovado final" in s:
        return "background-color: #2ecc71; color: white;"
    elif "aprovad" in s and "aguardando" not in s:
        return "background-color: #2980b9; color: white;"
    elif "devolvid" in s or "retorno" in s:
        return "background-color: #e67e22; color: white;"
    elif "em analise" in s or "aguardando" in s:
        return "background-color: #f39c12; color: black;"
    elif "execucao" in s:
        return "background-color: #8e44ad; color: white;"
    elif "infraestrutura" in s:
        return "background-color: #16a085; color: white;"
    return ""


def format_status_html(status_text):
    color = apply_status_color(status_text)
    if color:
        return f'<span style="{color} padding: 2px 8px; border-radius: 4px; font-size: 12px;">{status_text}</span>'
    return status_text


def display_photos(foto_data):
    if not foto_data:
        return
    fotos = str(foto_data).split('|')
    if len(fotos) == 1 and fotos[0].startswith("http"):
        st.image(fotos[0], width=300)
    elif fotos:
        cols = st.columns(min(len(fotos), 3))
        for i, foto in enumerate(fotos[:3]):
            with cols[i]:
                if foto.startswith("data:image"):
                    st.image(foto, caption=f"Foto {i+1}", width=250)
                elif foto.startswith("http"):
                    st.image(foto, caption=f"Foto {i+1}", width=250)


def get_flow_for_om(om_name):
    om_resolved = resolve_om(om_name)
    return CONFIG_OMS.get(om_resolved, {}).get("flow", [])


def can_user_approve(user_funcao, row_status, row_registro, flow):
    if not flow or user_funcao not in flow:
        return False
    idx = flow.index(user_funcao)
    if idx == 0:
        return row_status in ("Em Aberto", "Rascunho") or (
            "Devolvido" in row_status and idx == 0
        )
    else:
        return row_status == f"Aguardando {user_funcao}"


def get_next_role_in_flow(user_funcao, flow, row_registro=""):
    if not flow or user_funcao not in flow:
        return None, None
    idx = flow.index(user_funcao)
    if idx >= len(flow) - 1:
        return "Aprovado Final", None
    next_role = flow[idx + 1]
    if next_role == "Aprovado Final":
        return "Aprovado Final", None
    return f"Aguardando {next_role}", next_role


def get_return_options(user_funcao, flow):
    if not flow or user_funcao not in flow:
        return []
    idx = flow.index(user_funcao)
    options = []
    for i in range(idx):
        if i == 0:
            options.append((flow[i], "Devolvido p/ Correção"))
        else:
            options.append((flow[i], f"Aguardando {flow[i]}"))
    return options


st.set_page_config(
    page_title="Sistema de Solicitação de Serviços",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background-color: #0d1f14; }
    .stSidebar { background-color: #143324; }
    h1, h2, h3, h4, h5, h6 { color: #f5f6fa !important; }
    .stMarkdown { color: #f5f6fa; }
    div[data-testid="stForm"] { border: 1px solid #2ecc71; border-radius: 8px; padding: 10px; }
    .stButton > button { 
        background-color: #2ecc71; color: white; border-radius: 6px; 
        border: none; padding: 6px 16px; font-weight: bold;
    }
    .stButton > button:hover { background-color: #27ae60; }
    div[data-testid="stMetric"] { 
        background-color: #143324; padding: 12px; border-radius: 8px; 
        border: 1px solid #2ecc71;
    }
    .block-container { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)

init_session_state()
manager = get_manager()


if not st.session_state.logged_in:
    tab_login, tab_cadastro = st.tabs(["Login", "Cadastro"])

    with tab_login:
        st.markdown("### 🔐 Acessar Sistema")
        with st.form("login_form"):
            identidade = st.text_input("Identidade (matrícula)")
            senha = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", use_container_width=True)

            if submitted:
                if not identidade or not senha:
                    st.error("Preencha identidade e senha.")
                elif not manager or not manager.is_connected:
                    st.error("Sistema offline. Não é possível fazer login.")
                else:
                    users = manager.get_users()
                    identidade_clean = str(identidade).strip().lstrip("0")
                    found_user = None
                    for u in users:
                        uid = str(u.get("Identidade", "")).strip().lstrip("0")
                        if uid == identidade_clean:
                            found_user = u
                            break

                    if not found_user:
                        st.error("Usuário não encontrado.")
                    elif found_user.get("Status", "") == "Inativo":
                        st.error("Usuário inativo. Contate o administrador.")
                    else:
                        stored = found_user.get("Senha", "")
                        if verificar_senha(senha, stored):
                            st.session_state.logged_in = True
                            st.session_state.user_data = found_user
                            st.rerun()
                        else:
                            st.error("Senha incorreta.")

    with tab_cadastro:
        st.markdown("### 📝 Cadastrar Novo Usuário")

        om_options = ["Selecione a OM..."] + list(CONFIG_OMS.keys())
        om_cad = st.selectbox("Organização Militar", om_options, key="cad_om")

        funcao_options = ["Selecione a Função..."]
        if om_cad and om_cad != "Selecione a OM..." and om_cad in CONFIG_OMS:
            funcao_options = CONFIG_OMS[om_cad].get("roles", ["Selecione a Função..."])

        funcao_cad = st.selectbox("Função", funcao_options, key="cad_funcao")

        with st.form("cadastro_form"):
            nome = st.text_input("Nome completo")
            cad_identidade = st.text_input("Identidade (matrícula)")
            cad_senha = st.text_input("Senha", type="password")
            cad_senha2 = st.text_input("Confirmar senha", type="password")

            cad_submitted = st.form_submit_button("Cadastrar", use_container_width=True)

            if cad_submitted:
                if not all([om_cad, funcao_cad, nome, cad_identidade, cad_senha]):
                    st.error("Preencha todos os campos.")
                elif om_cad == "Selecione a OM...":
                    st.error("Selecione uma OM.")
                elif funcao_cad == "Selecione a Função...":
                    st.error("Selecione uma função.")
                elif cad_senha != cad_senha2:
                    st.error("As senhas não conferem.")
                elif len(cad_senha) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                elif not manager or not manager.is_connected:
                    st.error("Sistema offline. Não é possível cadastrar.")
                else:
                    ok, msg = manager.add_user(
                        resolve_om(om_cad), nome, cad_identidade, resolve_role(funcao_cad), cad_senha
                    )
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

else:
    user = st.session_state.user_data
    user_funcao = user.get("Funcao", "")
    user_om = user.get("OM", "")
    user_nome = user.get("Nome", "")
    user_identidade = user.get("Identidade", "")

    pode_criar = user_funcao in ROLES_PODEM_CRIAR_SOLICITACAO
    is_admin = user_funcao == "Administrador da OM"

    with st.sidebar:
        st.markdown(f"### 👤 {user_nome}")
        st.caption(f"**Função:** {user_funcao}")
        st.caption(f"**OM:** {user_om}")
        st.markdown("---")

        if st.button("🏠 Início", use_container_width=True, key="btn_inicio"):
            st.session_state.page = "solicitacoes"
            st.session_state.editing_id = None
            st.rerun()

        if pode_criar:
            if st.button("➕ Nova Solicitação", use_container_width=True, key="btn_nova"):
                st.session_state.page = "nova_solicitacao"
                st.session_state.editing_id = None
                st.rerun()

        if st.button("📊 Painel de Aprovações", use_container_width=True, key="btn_aprov"):
            st.session_state.page = "aprovacoes"
            st.rerun()

        if is_admin:
            if st.button("👥 Gerenciar Usuários", use_container_width=True, key="btn_users"):
                st.session_state.page = "usuarios"
                st.rerun()

        st.markdown("---")
        if st.button("🚪 Sair", use_container_width=True, key="btn_sair"):
            st.session_state.logged_in = False
            st.session_state.user_data = None
            st.rerun()

    if st.session_state.page == "solicitacoes":
        st.markdown("## 📋 Minhas Solicitações")

        if not manager or not manager.is_connected:
            st.error("Sistema offline. Verifique a conexão com o Supabase.")
            st.stop()

        data = manager.get_data_from_sheet("Demandas")
        if len(data) <= 1:
            st.info("Nenhuma solicitação encontrada.")
        else:
            rows = data[1:]
            hidden_ids_str = user.get("HiddenIDs", "") or ""
            hidden_ids = [h.strip() for h in hidden_ids_str.split(",") if h.strip()]

            my_requests = []
            for row in rows:
                row_id = row[0] if len(row) > 0 else ""
                row_solicitante = row[3] if len(row) > 3 else ""
                row_om = row[8] if len(row) > 8 else ""
                row_status = row[2] if len(row) > 2 else ""

                if row_id in hidden_ids:
                    continue

                is_mine = (row_solicitante == user_nome and row_om == user_om)
                is_in_my_flow = False

                flow = get_flow_for_om(row_om)
                if flow and user_funcao in flow:
                    idx = flow.index(user_funcao)
                    if row_status == f"Aguardando {user_funcao}":
                        is_in_my_flow = True
                    elif idx == 0 and row_status in ("Em Aberto", "Rascunho"):
                        is_in_my_flow = True
                    elif idx == 0 and "Devolvido" in row_status:
                        is_in_my_flow = True

                if is_mine or is_in_my_flow:
                    my_requests.append(row)

            if not my_requests:
                st.info("Nenhuma solicitação para exibir.")
            else:
                for idx, row in enumerate(my_requests):
                    row_id = row[0] if len(row) > 0 else ""
                    row_data = row[1] if len(row) > 1 else ""
                    row_status = row[2] if len(row) > 2 else ""
                    row_solicitante = row[3] if len(row) > 3 else ""
                    row_local = row[4] if len(row) > 4 else ""
                    row_tipo = row[5] if len(row) > 5 else ""
                    row_desc = row[6] if len(row) > 6 else ""
                    row_urgencia = row[7] if len(row) > 7 else ""
                    row_om = row[8] if len(row) > 8 else ""
                    row_foto = row[10] if len(row) > 10 else ""
                    row_registro = row[12] if len(row) > 12 else ""

                    status_html = format_status_html(row_status)

                    with st.expander(f"**{row_id}** | {row_tipo} | {row_local}", expanded=False):
                        col1, col2 = st.columns([2, 1])
                        with col1:
                            st.markdown(f"**Status:** {status_html}", unsafe_allow_html=True)
                            st.markdown(f"**Data:** {row_data}")
                            st.markdown(f"**Solicitante:** {row_solicitante}")
                            st.markdown(f"**Local:** {row_local}")
                            st.markdown(f"**Tipo:** {row_tipo}")
                            st.markdown(f"**Urgência:** {row_urgencia}")
                            st.markdown(f"**Descrição:** {row_desc}")
                            if row_foto:
                                display_photos(row_foto)
                        with col2:
                            is_owner = (row_solicitante == user_nome and row_om == user_om)

                            flow = get_flow_for_om(row_om)
                            user_can_approve = can_user_approve(user_funcao, row_status, row_registro, flow)
                            next_status, next_role = get_next_role_in_flow(user_funcao, flow, row_registro)

                            if user_can_approve and next_status:
                                if next_status == "Aprovado Final":
                                    if st.button("✅ Aprovar Final", key=f"aprovfinal_sol_{row_id}", use_container_width=True):
                                        ok, msg = manager.update_status(row_id, "Aprovado Final", f"Aprovado por {user_nome}", user_nome)
                                        if ok:
                                            st.success(msg)
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(msg)
                                else:
                                    if st.button(f"✅ Enviar p/ {next_role}", key=f"aprov_sol_{row_id}", use_container_width=True):
                                        ok, msg = manager.update_status(row_id, next_status, f"Encaminhado para {next_role} por {user_nome}", user_nome, "APROVADO")
                                        if ok:
                                            st.success(msg)
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(msg)

                            if is_owner and row_status in ("Em Aberto", "Rascunho"):
                                if st.button("✏️ Editar", key=f"edit_sol_{row_id}", use_container_width=True):
                                    st.session_state.editing_id = row_id
                                    st.session_state.page = "nova_solicitacao"
                                    st.rerun()

                            if is_owner and row_status in ("Em Aberto", "Rascunho"):
                                if st.button("🗑️ Excluir", key=f"del_sol_{row_id}", use_container_width=True):
                                    ok, msg = manager.delete_solicitacao(row_id)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                            return_options = get_return_options(user_funcao, flow)
                            if user_can_approve and return_options:
                                with st.popover("↩️ Devolver"):
                                    st.markdown("**Devolver para:**")
                                    for role, label in return_options:
                                        if st.button(label, key=f"ret_sol_{row_id}_{role}", use_container_width=True):
                                            ok, msg = manager.update_status(row_id, f"Devolvido", f"Devolvido por {user_nome}", user_nome, "RETORNO")
                                            if ok:
                                                st.success(msg)
                                                time.sleep(0.5)
                                                st.rerun()
                                            else:
                                                st.error(msg)

                            if is_owner and "Devolvido" in row_status and not user_can_approve:
                                if st.button("✏️ Editar", key=f"edit_dev_sol_{row_id}", use_container_width=True):
                                    st.session_state.editing_id = row_id
                                    st.session_state.page = "nova_solicitacao"
                                    st.rerun()

                            if user_funcao == FUNCAO_SECAO_SERVICOS_GERAIS and row_status == STATUS_ANALISE_SERVICOS_GERAIS:
                                c1, c2 = st.columns(2)
                                with c1:
                                    if st.button("🔨 Executar", key=f"exec_sol_{row_id}", use_container_width=True):
                                        ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(row_id, TAG_PO_EXECUTA, user_nome)
                                        if ok:
                                            st.success(msg)
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(msg)
                                with c2:
                                    if st.button("🚫 Não Executar", key=f"nao_sol_{row_id}", use_container_width=True):
                                        ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(row_id, TAG_PO_NAO_EXECUTA, user_nome)
                                        if ok:
                                            st.success(msg)
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(msg)

                            if user_funcao in (FUNCAO_FISC_ADM_BASE, FUNCAO_SECAO_SERVICOS_GERAIS) and row_status == STATUS_EM_EXECUCAO_PO:
                                if st.button("✅ Concluir (PO)", key=f"conclpo_sol_{row_id}", use_container_width=True):
                                    ok, msg = manager.concluir_servico_po(row_id, user_nome)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                            if user_funcao == "Chefe da Seção de Infraestrutura" and row_status == STATUS_EM_EXECUCAO_PO:
                                if st.button("✅ Concluir (Infra)", key=f"conclinfra_sol_{row_id}", use_container_width=True):
                                    ok, msg = manager.concluir_servico_infraestrutura(row_id, user_nome)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                            if st.button("📋 Detalhar", key=f"det_sol_{row_id}", use_container_width=True):
                                st.session_state[f"show_det_{row_id}"] = True

                        if st.session_state.get(f"show_det_{row_id}", False):
                            show_detalhamento(row_id)

                        if row_registro:
                            st.markdown("---")
                            st.markdown("**Registro de Ações:**")
                            for line in str(row_registro).split("\n"):
                                if line.strip():
                                    st.text(line.strip())

    elif st.session_state.page == "nova_solicitacao":
        editing_id = st.session_state.editing_id
        if editing_id:
            st.markdown(f"## ✏️ Editar Solicitação: {editing_id}")
        else:
            st.markdown("## ➕ Nova Solicitação")

        data = manager.get_data_from_sheet("Demandas") if manager and manager.is_connected else []
        existing_data = None
        if editing_id and len(data) > 1:
            for row in data[1:]:
                if row[0] == editing_id:
                    existing_data = row
                    break

        with st.form("solicitacao_form"):
            local = st.text_input("Local*", value=existing_data[4] if existing_data else "")

            tipo_idx = 0
            if existing_data and existing_data[5] in TIPOS_ORIGINAIS:
                tipo_idx = TIPOS_ORIGINAIS.index(existing_data[5]) + 1
            tipo = st.selectbox("Tipo*", ["Selecione..."] + TIPOS_ORIGINAIS, index=tipo_idx)

            urg_idx = 0
            if existing_data and existing_data[7] in URGENCIAS_ORIGINAIS:
                urg_idx = URGENCIAS_ORIGINAIS.index(existing_data[7]) + 1
            urgencia = st.selectbox("Urgência*", ["Selecione..."] + URGENCIAS_ORIGINAIS, index=urg_idx)

            descricao = st.text_area("Descrição*", value=existing_data[6] if existing_data else "", height=120)

            fotos_upload = st.file_uploader(
                "📎 Anexar Fotos (Máx 3 - 1MB cada)",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key="fotos_upload",
            )

            if fotos_upload and len(fotos_upload) > 3:
                st.warning("Máximo de 3 fotos. Apenas as 3 primeiras serão utilizadas.")
                fotos_upload = fotos_upload[:3]

            submitted = st.form_submit_button("Enviar Solicitação" if not editing_id else "Atualizar", use_container_width=True)

            if submitted:
                if not local or tipo == "Selecione..." or urgencia == "Selecione..." or not descricao:
                    st.error("Preencha todos os campos obrigatórios (*).")
                else:
                    fotos_base64 = []
                    if fotos_upload:
                        for foto in fotos_upload[:3]:
                            encoded = compress_and_encode_image(foto)
                            if encoded:
                                fotos_base64.append(encoded)
                            else:
                                st.warning(f"Não foi possível processar a foto: {foto.name}")

                    foto_final = "|".join(fotos_base64) if fotos_base64 else ""

                    if editing_id and existing_data:
                        foto_existente = existing_data[10] if len(existing_data) > 10 else ""
                        if not fotos_base64 and foto_existente:
                            foto_final = foto_existente

                    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                    if editing_id:
                        dados = [now, "Em Aberto", user_nome, local, tipo, descricao, urgencia, user_om, foto_final]
                        ok, msg = manager.update_solicitacao(editing_id, dados)
                    else:
                        new_id = generate_id()
                        data_list = [new_id, now, "Em Aberto", user_nome, local, tipo, descricao, urgencia, user_om, foto_final]
                        ok, msg = manager.add_solicitacao(data_list)

                    if ok:
                        st.success(msg)
                        st.session_state.page = "solicitacoes"
                        st.session_state.editing_id = None
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(msg)

        if st.button("Cancelar"):
            st.session_state.page = "solicitacoes"
            st.session_state.editing_id = None
            st.rerun()

    elif st.session_state.page == "aprovacoes":
        st.markdown("## 📊 Painel de Aprovações")

        if not manager or not manager.is_connected:
            st.error("Sistema offline.")
            st.stop()

        tabs = list(APROVACOES_BLOCOS.keys())
        tab_labels = [APROVACOES_BLOCOS[t] for t in tabs]
        selected_tab = st.tabs(tab_labels)

        for i, (tab_key, tab_label) in enumerate(zip(tabs, tab_labels)):
            with selected_tab[i]:
                st.markdown(f"### {tab_label}")

                data = manager.get_aproved_data(tab_key)
                if len(data) <= 1:
                    st.info("Nenhuma demanda nesta fila.")
                    continue

                rows = data[1:]

                for row in rows:
                    row_id = row[0] if len(row) > 0 else ""
                    row_status = row[2] if len(row) > 2 else ""
                    row_solicitante = row[3] if len(row) > 3 else ""
                    row_local = row[4] if len(row) > 4 else ""
                    row_tipo = row[5] if len(row) > 5 else ""
                    row_desc = row[6] if len(row) > 6 else ""
                    row_urgencia = row[7] if len(row) > 7 else ""
                    row_foto = row[10] if len(row) > 10 else ""
                    row_parecer = row[11] if len(row) > 11 else ""
                    row_registro = row[12] if len(row) > 12 else ""

                    status_html = format_status_html(row_status)

                    with st.expander(f"**{row_id}** | {row_tipo} | {row_local}", expanded=False):
                        st.markdown(f"**Status:** {status_html}", unsafe_allow_html=True)
                        st.markdown(f"**Solicitante:** {row_solicitante}")
                        st.markdown(f"**Urgência:** {row_urgencia}")
                        st.markdown(f"**Descrição:** {row_desc}")
                        if row_foto:
                            display_photos(row_foto)

                        if row_parecer:
                            st.markdown(f"**Parecer PO:** {row_parecer}")

                        btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)

                        with btn_col1:
                            if st.button("⬆️", key=f"up_aprov_{tab_key}_{row_id}", help="Subir prioridade"):
                                manager.update_aproved_priority(tab_key, row_id, -1)
                                st.rerun()
                        with btn_col2:
                            if st.button("⬇️", key=f"down_aprov_{tab_key}_{row_id}", help="Descer prioridade"):
                                manager.update_aproved_priority(tab_key, row_id, 1)
                                st.rerun()
                        with btn_col3:
                            if st.button("🗑️", key=f"del_aprov_{tab_key}_{row_id}", help="Remover"):
                                manager.delete_item_from_aproved(tab_key, row_id)
                                st.rerun()
                        with btn_col4:
                            if st.button("📋", key=f"det_aprov_{tab_key}_{row_id}", help="Detalhar"):
                                st.session_state[f"show_det_{row_id}"] = True

                        if st.session_state.get(f"show_det_{row_id}", False):
                            show_detalhamento(row_id)

                        if user_funcao == FUNCAO_SECAO_SERVICOS_GERAIS and row_status == STATUS_ANALISE_SERVICOS_GERAIS:
                            exec_col, nao_col = st.columns(2)
                            with exec_col:
                                if st.button("🔨 Executar", key=f"exec_aprov_{row_id}", use_container_width=True):
                                    ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(row_id, TAG_PO_EXECUTA, user_nome)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                            with nao_col:
                                if st.button("🚫 Não Executar", key=f"nao_aprov_{row_id}", use_container_width=True):
                                    ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(row_id, TAG_PO_NAO_EXECUTA, user_nome)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                        if user_funcao in (FUNCAO_FISC_ADM_BASE, FUNCAO_SECAO_SERVICOS_GERAIS) and row_status == STATUS_EM_EXECUCAO_PO:
                            if st.button("✅ Concluir Serviço", key=f"concl_aprov_{row_id}", use_container_width=True):
                                ok, msg = manager.concluir_servico_po(row_id, user_nome)
                                if ok:
                                    st.success(msg)
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error(msg)

                        if row_registro:
                            st.markdown("---")
                            st.markdown("**Registro:**")
                            for line in str(row_registro).split("\n"):
                                if line.strip():
                                    st.text(line.strip())

        st.markdown("---")
        st.markdown("### 📈 Fluxograma de Aprovação (Simplificado)")
        flow_om = CONFIG_OMS.get(user_om, {}).get("flow", [])
        if flow_om:
            flow_html = " → ".join([f"**{step}**" for step in flow_om])
            st.markdown(f"🔄 {flow_html}")
        else:
            st.info("Fluxo não configurado para sua OM.")

    elif st.session_state.page == "usuarios":
        if not is_admin:
            st.error("Acesso restrito a Administradores da OM.")
            st.stop()

        st.markdown("## 👥 Gerenciar Usuários")

        if not manager or not manager.is_connected:
            st.error("Sistema offline.")
            st.stop()

        users = manager.get_users()
        om_users = [u for u in users if u.get("OM") == user_om]

        if not om_users:
            st.info("Nenhum usuário cadastrado para sua OM.")
        else:
            for u in om_users:
                u_nome = u.get("Nome", "")
                u_ident = u.get("Identidade", "")
                u_funcao = u.get("Funcao", "")
                u_status = u.get("Status", "")

                with st.expander(f"👤 {u_nome} | {u_funcao} | {u_status}", expanded=False):
                    st.markdown(f"**Identidade:** {u_ident}")
                    st.markdown(f"**OM:** {u.get('OM', '')}")
                    st.markdown(f"**Status:** {u_status}")

                    if u_ident != user_identidade:
                        if st.button(f"🗑️ Excluir {u_nome}", key=f"deluser_{u_ident}"):
                            ok, msg = manager.delete_user(u_ident)
                            if ok:
                                st.success(msg)
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(msg)

        st.markdown("---")
        st.markdown("### ➕ Cadastrar Novo Usuário")

        om_options_admin = ["Selecione a OM..."] + list(CONFIG_OMS.keys())
        new_om = st.selectbox("OM", om_options_admin, key="admin_cad_om")

        new_funcao_options = ["Selecione a Função..."]
        if new_om and new_om != "Selecione a OM..." and new_om in CONFIG_OMS:
            new_funcao_options = CONFIG_OMS[new_om].get("roles", ["Selecione a Função..."])

        new_funcao = st.selectbox("Função", new_funcao_options, key="admin_cad_funcao")

        with st.form("admin_cadastro_form"):
            new_nome = st.text_input("Nome completo")
            new_ident = st.text_input("Identidade (matrícula)")
            new_senha = st.text_input("Senha", type="password")

            if st.form_submit_button("Cadastrar", use_container_width=True):
                if not all([new_om, new_funcao, new_nome, new_ident, new_senha]):
                    st.error("Preencha todos os campos.")
                elif new_om == "Selecione a OM...":
                    st.error("Selecione uma OM.")
                elif new_funcao == "Selecione a Função...":
                    st.error("Selecione uma função.")
                elif len(new_senha) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                else:
                    ok, msg = manager.add_user(resolve_om(new_om), new_nome, new_ident, resolve_role(new_funcao), new_senha)
                    if ok:
                        st.success(msg)
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(msg)


def show_detalhamento(demanda_id):
    st.markdown(f"#### 📋 Detalhamento - {demanda_id}")

    itens = []
    if manager and manager.is_connected:
        itens = manager.get_detalhamento(demanda_id)

    insumos_db = []
    composicoes_db = []
    try:
        if os.path.exists(SINAPI_INSUMOS_FILE):
            with open(SINAPI_INSUMOS_FILE, "r", encoding="utf-8") as f:
                insumos_db = json.load(f)
        if os.path.exists(SINAPI_COMPOSICOES_FILE):
            with open(SINAPI_COMPOSICOES_FILE, "r", encoding="utf-8") as f:
                composicoes_db = json.load(f)
    except Exception:
        pass

    if itens:
        df_data = []
        for item in itens:
            df_data.append({
                "Código": item.get("codigo", ""),
                "Descrição": item.get("descricao", ""),
                "Unidade": item.get("unidade", ""),
                "Qtd": item.get("quantidade", 0),
                "Unit. (R$)": item.get("preco_unitario", 0),
                "Total (R$)": item.get("quantidade", 0) * item.get("preco_unitario", 0),
            })

        import pandas as pd
        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True)

        total = df["Total (R$)"].sum()
        st.metric("Total Geral", f"R$ {total:,.2f}")
    else:
        st.info("Nenhum item detalhado para esta demanda.")

    st.session_state[f"show_det_{demanda_id}"] = True
