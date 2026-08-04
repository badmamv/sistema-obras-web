import streamlit as st
import json
import os
import re
import hashlib
import base64
import datetime
import time
import io

from constants import (
    CONFIG_OMS, SheetColumns, HEADER_DEMANDA, resolve_om, resolve_role,
    GLOBAL_UNIQUE_ROLES, ROLES_PODEM_CRIAR_SOLICITACAO, ROLES_COM_APROVACOES,
    FUNCAO_SECAO_SERVICOS_GERAIS, FUNCAO_FISC_ADM_BASE, APROVACOES_BLOCOS,
    STATUS_ANALISE_SERVICOS_GERAIS, STATUS_ANALISE_INFRAESTRUTURA,
    STATUS_RECEBIDO_INFRAESTRUTURA, TAG_PO_EXECUTA, TAG_PO_NAO_EXECUTA,
    STATUS_EM_EXECUCAO_PO, STATUS_CONCLUIDO_PO, STATUS_CONCLUIDO_INFRA,
    status_para_bloco_aprovacao, status_alvos_bloco_aprovacao,
    extrair_parecer_po, descricao_original, gerar_hash_senha, verificar_senha,
    SINAPI_INSUMOS_FILE, SINAPI_COMPOSICOES_FILE,
)
from supabase_manager import SupabaseManager, HEADER_DEMANDA as SB_HEADER

SUPABASE_CONFIG_FILE = "supabase_config.json"


def load_supabase_config():
    try:
        if hasattr(st, 'secrets') and 'supabase' in st.secrets:
            return {
                "use_supabase": True,
                "supabase_url": st.secrets.supabase.supabase_url,
                "supabase_key": st.secrets.supabase.supabase_key,
                "supabase_service_key": st.secrets.supabase.get("supabase_service_key", st.secrets.supabase.supabase_key),
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
    if config.get("use_supabase", False):
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
                st.warning(f"Falha Supabase: {msg}. Usando modo offline.")
        except Exception as e:
            st.warning(f"Erro Supabase: {e}. Usando modo offline.")
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


def apply_status_color(status_text):
    if not status_text:
        return ""
    s = str(status_text).lower()
    if "conclu" in s:
        return "background-color: #27ae60; color: white;"
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


st.set_page_config(
    page_title="Sistema de Solicitacao de Servicos",
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
            identidade = st.text_input("Identidade (matricula)")
            senha = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", use_container_width=True)

            if submitted:
                if not identidade or not senha:
                    st.error("Preencha identidade e senha.")
                elif not manager or not manager.is_connected:
                    st.error("Sistema offline. Nao e possivel fazer login.")
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
                        st.error("Usuario nao encontrado.")
                    elif found_user.get("Status", "") == "Inativo":
                        st.error("Usuario inativo. Contate o administrador.")
                    else:
                        stored = found_user.get("Senha", "")
                        if verificar_senha(senha, stored):
                            st.session_state.logged_in = True
                            st.session_state.user_data = found_user
                            st.rerun()
                        else:
                            st.error("Senha incorreta.")

    with tab_cadastro:
        st.markdown("### 📝 Cadastrar Novo Usuario")

        om_options = ["Selecione a OM..."] + list(CONFIG_OMS.keys())
        om_cad = st.selectbox("Organizacao Militar", om_options, key="cad_om")

        funcao_options = ["Selecione a Funcao..."]
        if om_cad and om_cad != "Selecione a OM..." and om_cad in CONFIG_OMS:
            funcao_options = CONFIG_OMS[om_cad].get("roles", ["Selecione a Funcao..."])

        funcao_cad = st.selectbox("Funcao", funcao_options, key="cad_funcao")

        with st.form("cadastro_form"):
            nome = st.text_input("Nome completo")
            cad_identidade = st.text_input("Identidade (matricula)")
            cad_senha = st.text_input("Senha", type="password")
            cad_senha2 = st.text_input("Confirmar senha", type="password")

            cad_submitted = st.form_submit_button("Cadastrar", use_container_width=True)

            if cad_submitted:
                if not all([om_cad, funcao_cad, nome, cad_identidade, cad_senha]):
                    st.error("Preencha todos os campos.")
                elif om_cad == "Selecione a OM...":
                    st.error("Selecione uma OM.")
                elif funcao_cad == "Selecione a Funcao...":
                    st.error("Selecione uma funcao.")
                elif cad_senha != cad_senha2:
                    st.error("As senhas nao conferem.")
                elif len(cad_senha) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                elif not manager or not manager.is_connected:
                    st.error("Sistema offline. Nao e possivel cadastrar.")
                else:
                    om_resolved = resolve_om(om_cad)
                    funcao_resolved = resolve_role(funcao_cad)
                    ok, msg = manager.add_user(
                        om_resolved, nome, cad_identidade, funcao_resolved, cad_senha
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
    tem_aprovacoes = user_funcao in ROLES_COM_APROVACOES
    is_admin = user_funcao == "Administrador da OM"

    with st.sidebar:
        st.markdown(f"### 👤 {user_nome}")
        st.caption(f"**Funcao:** {user_funcao}")
        st.caption(f"**OM:** {user_om}")
        st.markdown("---")

        if st.button("🏠 Inicio", use_container_width=True):
            st.session_state.page = "solicitacoes"
            st.session_state.editing_id = None
            st.rerun()

        if pode_criar:
            if st.button("➕ Nova Solicitacao", use_container_width=True):
                st.session_state.page = "nova_solicitacao"
                st.session_state.editing_id = None
                st.rerun()

        if tem_aprovacoes:
            if st.button("📊 Painel de Aprovacoes", use_container_width=True):
                st.session_state.page = "aprovacoes"
                st.rerun()

        if is_admin:
            if st.button("👥 Gerenciar Usuarios", use_container_width=True):
                st.session_state.page = "usuarios"
                st.rerun()

        st.markdown("---")
        if st.button("🚪 Sair", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user_data = None
            st.rerun()

    if st.session_state.page == "solicitacoes":
        st.markdown("## 📋 Minhas Solicitacoes")

        if not manager or not manager.is_connected:
            st.error("Sistema offline. Verifique a conexao com o Supabase.")
            st.stop()

        data = manager.get_data_from_sheet("Demandas")
        if len(data) <= 1:
            st.info("Nenhuma solicitacao encontrada.")
        else:
            header = data[0]
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

                if tem_aprovacoes:
                    flow_steps = CONFIG_OMS.get(user_om, {}).get("flow", [])
                    try:
                        my_idx = flow_steps.index(user_funcao)
                        for k in range(my_idx + 1, len(flow_steps)):
                            role_check = flow_steps[k]
                            if f"APROVADO {role_check}" in str(row[12] if len(row) > 12 else ""):
                                is_in_my_flow = True
                                break
                            if f"RETORNO {role_check}" in str(row[12] if len(row) > 12 else ""):
                                is_in_my_flow = True
                                break
                    except (ValueError, IndexError):
                        pass

                if is_mine or is_in_my_flow:
                    my_requests.append(row)

            if not my_requests:
                st.info("Nenhuma solicitacao para exibir.")
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
                            st.markdown(f"**Urgencia:** {row_urgencia}")
                            st.markdown(f"**Descricao:** {row_desc}")
                        with col2:
                            is_owner = (row_solicitante == user_nome and row_om == user_om)

                            if is_owner and row_status in ("Em Aberto", "Rascunho"):
                                if st.button("✏️ Editar", key=f"edit_{row_id}", use_container_width=True):
                                    st.session_state.editing_id = row_id
                                    st.session_state.page = "nova_solicitacao"
                                    st.rerun()

                            if is_owner and row_status in ("Em Aberto", "Rascunho"):
                                if st.button("🗑️ Excluir", key=f"del_{row_id}", use_container_width=True):
                                    ok, msg = manager.delete_solicitacao(row_id)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                            if is_owner and row_status == "Devolvido":
                                if st.button("↩️ Devolver", key=f"return_{row_id}", use_container_width=True):
                                    st.session_state[f"return_{row_id}"] = True

                            if tem_aprovacoes:
                                flow_steps = CONFIG_OMS.get(user_om, {}).get("flow", [])
                                try:
                                    my_idx = flow_steps.index(user_funcao)
                                    next_role = flow_steps[my_idx + 1] if my_idx + 1 < len(flow_steps) else None
                                    if next_role:
                                        if st.button(f"✅ Aprovar p/ {next_role}", key=f"aprov_{row_id}", use_container_width=True):
                                            ok, msg = manager.update_status(
                                                row_id,
                                                f"Aprovado - {next_role}",
                                                motivo=f"Aprovado por {user_nome}",
                                                quem=user_nome,
                                            )
                                            if ok:
                                                st.success(msg)
                                                time.sleep(0.5)
                                                st.rerun()
                                            else:
                                                st.error(msg)
                                except (ValueError, IndexError):
                                    pass

                            if user_funcao == FUNCAO_SECAO_SERVICOS_GERAIS and row_status == STATUS_ANALISE_SERVICOS_GERAIS:
                                c1, c2 = st.columns(2)
                                with c1:
                                    if st.button("🔨 Executar", key=f"exec_{row_id}", use_container_width=True):
                                        ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(
                                            row_id, TAG_PO_EXECUTA, user_nome
                                        )
                                        if ok:
                                            st.success(msg)
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(msg)
                                with c2:
                                    if st.button("🚫 Nao Executar", key=f"nao_{row_id}", use_container_width=True):
                                        ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(
                                            row_id, TAG_PO_NAO_EXECUTA, user_nome
                                        )
                                        if ok:
                                            st.success(msg)
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(msg)

                            if user_funcao in (FUNCAO_FISC_ADM_BASE, FUNCAO_SECAO_SERVICOS_GERAIS) and row_status == STATUS_EM_EXECUCAO_PO:
                                if st.button("✅ Concluir (PO)", key=f"conclpo_{row_id}", use_container_width=True):
                                    ok, msg = manager.concluir_servico_po(row_id, user_nome)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                            if user_funcao == "Chefe da Secao de Infraestrutura" and row_status == STATUS_EM_EXECUCAO_PO:
                                if st.button("✅ Concluir (Infra)", key=f"conclinfra_{row_id}", use_container_width=True):
                                    ok, msg = manager.concluir_servico_infraestrutura(row_id, user_nome)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                            if st.button("📋 Detalhar", key=f"det_{row_id}", use_container_width=True):
                                st.session_state[f"show_det_{row_id}"] = True

                        if st.session_state.get(f"show_det_{row_id}", False):
                            show_detalhamento(row_id)

                        if st.session_state.get(f"return_{row_id}", False):
                            with st.form(f"return_form_{row_id}"):
                                motivo = st.text_area("Motivo da devolucao")
                                if st.form_submit_button("Enviar Devolucao"):
                                    if motivo:
                                        ok, msg = manager.update_status(
                                            row_id,
                                            "Devolvido",
                                            motivo=motivo,
                                            quem=user_nome,
                                            prefix="RETORNO",
                                        )
                                        if ok:
                                            st.success(msg)
                                            st.session_state[f"return_{row_id}"] = False
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(msg)
                                    else:
                                        st.error("Informe o motivo.")

                        if row_registro:
                            st.markdown("---")
                            st.markdown("**Registro de Acoes:**")
                            for line in str(row_registro).split("\n"):
                                if line.strip():
                                    st.text(line.strip())

    elif st.session_state.page == "nova_solicitacao":
        editing_id = st.session_state.editing_id
        if editing_id:
            st.markdown(f"## ✏️ Editar Solicitacao: {editing_id}")
        else:
            st.markdown("## ➕ Nova Solicitacao")

        data = manager.get_data_from_sheet("Demandas") if manager and manager.is_connected else []
        existing_data = None
        if editing_id and len(data) > 1:
            for row in data[1:]:
                if row[0] == editing_id:
                    existing_data = row
                    break

        with st.form("solicitacao_form"):
            col1, col2 = st.columns(2)
            with col1:
                local = st.text_input("Local*", value=existing_data[4] if existing_data else "")
                tipo = st.selectbox("Tipo*", [
                    "Selecione...", "Material", "Servico", "Equipamento", "Manutencao", "Infraestrutura", "Outros"
                ], index=max(0, (
                    ["Selecione...", "Material", "Servico", "Equipamento", "Manutencao", "Infraestrutura", "Outros"].index(existing_data[5])
                    if existing_data and existing_data[5] in ["Material", "Servico", "Equipamento", "Manutencao", "Infraestrutura", "Outros"]
                    else 0
                )))
            with col2:
                urgencia = st.selectbox("Urgencia*", [
                    "Selecione...", "Baixa", "Media", "Alta", "Critica"
                ], index=max(0, (
                    ["Selecione...", "Baixa", "Media", "Alta", "Critica"].index(existing_data[7])
                    if existing_data and existing_data[7] in ["Baixa", "Media", "Alta", "Critica"]
                    else 0
                )))

            descricao = st.text_area("Descricao*", value=existing_data[6] if existing_data else "", height=120)

            submitted = st.form_submit_button("Enviar Solicitacao" if not editing_id else "Atualizar", use_container_width=True)

            if submitted:
                if not local or tipo == "Selecione..." or urgencia == "Selecione..." or not descricao:
                    st.error("Preencha todos os campos obrigatorios (*).")
                else:
                    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                    if editing_id:
                        dados = [now, "Em Aberto", user_nome, local, tipo, descricao, urgencia, user_om, ""]
                        ok, msg = manager.update_solicitacao(editing_id, dados)
                    else:
                        new_id = generate_id()
                        data_list = [new_id, now, "Em Aberto", user_nome, local, tipo, descricao, urgencia, user_om, ""]
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
        st.markdown("## 📊 Painel de Aprovacoes")

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

                header = data[0]
                rows = data[1:]

                for row in rows:
                    row_id = row[0] if len(row) > 0 else ""
                    row_status = row[2] if len(row) > 2 else ""
                    row_solicitante = row[3] if len(row) > 3 else ""
                    row_local = row[4] if len(row) > 4 else ""
                    row_tipo = row[5] if len(row) > 5 else ""
                    row_desc = row[6] if len(row) > 6 else ""
                    row_urgencia = row[7] if len(row) > 7 else ""
                    row_parecer = row[11] if len(row) > 11 else ""
                    row_registro = row[12] if len(row) > 12 else ""

                    status_html = format_status_html(row_status)

                    with st.expander(f"**{row_id}** | {row_tipo} | {row_local}", expanded=False):
                        st.markdown(f"**Status:** {status_html}", unsafe_allow_html=True)
                        st.markdown(f"**Solicitante:** {row_solicitante}")
                        st.markdown(f"**Urgencia:** {row_urgencia}")
                        st.markdown(f"**Descricao:** {row_desc}")

                        if row_parecer:
                            st.markdown(f"**Parecer PO:** {row_parecer}")

                        btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)

                        with btn_col1:
                            if st.button("⬆️", key=f"up_{tab_key}_{row_id}", help="Subir prioridade"):
                                manager.update_aproved_priority(tab_key, row_id, -1)
                                st.rerun()
                        with btn_col2:
                            if st.button("⬇️", key=f"down_{tab_key}_{row_id}", help="Descer prioridade"):
                                manager.update_aproved_priority(tab_key, row_id, 1)
                                st.rerun()
                        with btn_col3:
                            if st.button("🗑️", key=f"delap_{tab_key}_{row_id}", help="Remover"):
                                manager.delete_item_from_aproved(tab_key, row_id)
                                st.rerun()
                        with btn_col4:
                            if st.button("📋", key=f"detap_{tab_key}_{row_id}", help="Detalhar"):
                                st.session_state[f"show_det_{row_id}"] = True

                        if st.session_state.get(f"show_det_{row_id}", False):
                            show_detalhamento(row_id)

                        if user_funcao == FUNCAO_SECAO_SERVICOS_GERAIS and row_status == STATUS_ANALISE_SERVICOS_GERAIS:
                            exec_col, nao_col = st.columns(2)
                            with exec_col:
                                if st.button("🔨 Executar", key=f"execap_{row_id}", use_container_width=True):
                                    ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(
                                        row_id, TAG_PO_EXECUTA, user_nome
                                    )
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                            with nao_col:
                                if st.button("🚫 Nao Executar", key=f"naoap_{row_id}", use_container_width=True):
                                    ok, msg = manager.parecer_servicos_gerais_para_fisc_adm(
                                        row_id, TAG_PO_NAO_EXECUTA, user_nome
                                    )
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                        if user_funcao in (FUNCAO_FISC_ADM_BASE, FUNCAO_SECAO_SERVICOS_GERAIS) and row_status == STATUS_EM_EXECUCAO_PO:
                            if st.button("✅ Concluir Servico", key=f"conclap_{row_id}", use_container_width=True):
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
        st.markdown("### 📈 Fluxograma de Aprovacao (Simplificado)")
        flow_om = CONFIG_OMS.get(user_om, {}).get("flow", [])
        if flow_om:
            flow_html = " → ".join([f"**{step}**" for step in flow_om])
            st.markdown(f"🔄 {flow_html}")
        else:
            st.info("Fluxo nao configurado para sua OM.")

    elif st.session_state.page == "usuarios":
        if not is_admin:
            st.error("Acesso restrito a Administradores da OM.")
            st.stop()

        st.markdown("## 👥 Gerenciar Usuarios")

        if not manager or not manager.is_connected:
            st.error("Sistema offline.")
            st.stop()

        users = manager.get_users()
        om_users = [u for u in users if u.get("OM") == user_om]

        if not om_users:
            st.info("Nenhum usuario cadastrado para sua OM.")
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
        st.markdown("### ➕ Cadastrar Novo Usuario")

        om_options_admin = ["Selecione a OM..."] + list(CONFIG_OMS.keys())
        new_om = st.selectbox("OM", om_options_admin, key="admin_cad_om")

        new_funcao_options = ["Selecione a Funcao..."]
        if new_om and new_om != "Selecione a OM..." and new_om in CONFIG_OMS:
            new_funcao_options = CONFIG_OMS[new_om].get("roles", ["Selecione a Funcao..."])

        new_funcao = st.selectbox("Funcao", new_funcao_options, key="admin_cad_funcao")

        with st.form("admin_cadastro_form"):
            new_nome = st.text_input("Nome completo")
            new_ident = st.text_input("Identidade (matricula)")
            new_senha = st.text_input("Senha", type="password")

            if st.form_submit_button("Cadastrar", use_container_width=True):
                if not all([new_om, new_funcao, new_nome, new_ident, new_senha]):
                    st.error("Preencha todos os campos.")
                elif new_om == "Selecione a OM...":
                    st.error("Selecione uma OM.")
                elif new_funcao == "Selecione a Funcao...":
                    st.error("Selecione uma funcao.")
                elif len(new_senha) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                else:
                    om_resolved = resolve_om(new_om)
                    funcao_resolved = resolve_role(new_funcao)
                    ok, msg = manager.add_user(om_resolved, new_nome, new_ident, funcao_resolved, new_senha)
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
                "Codigo": item.get("codigo", ""),
                "Descricao": item.get("descricao", ""),
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
