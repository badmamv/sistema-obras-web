import streamlit as st
import json
import os
import re
import base64
import datetime
import time
import io
import pandas as pd
from PIL import Image

from constants import (
    CONFIG_OMS, SheetColumns, HEADER_DEMANDA, resolve_om, resolve_role,
    ROLE_ALIASES, OM_ALIASES, GLOBAL_UNIQUE_ROLES, ROLES_PODEM_CRIAR_SOLICITACAO,
    ROLES_COM_APROVACOES, FUNCAO_SECAO_SERVICOS_GERAIS, FUNCAO_FISC_ADM_BASE,
    APROVACOES_BLOCOS, STATUS_ANALISE_SERVICOS_GERAIS, STATUS_ANALISE_INFRAESTRUTURA,
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
            url = key = skey = ""
            if 'supabase' in st.secrets:
                url = st.secrets.supabase.get("supabase_url", "")
                key = st.secrets.supabase.get("supabase_key", "")
                skey = st.secrets.supabase.get("supabase_service_key", "")
            elif 'supabase_url' in st.secrets:
                url = st.secrets.get("supabase_url", "")
                key = st.secrets.get("supabase_key", "")
                skey = st.secrets.get("supabase_service_key", "")
            if url and key:
                return {"use_supabase": True, "supabase_url": url,
                        "supabase_key": skey or key, "supabase_service_key": skey or key,
                        "poll_interval_ms": 3000}
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
        return mgr if success else None
    except Exception:
        return None


def get_manager():
    if "manager" not in st.session_state:
        st.session_state.manager = create_manager()
    return st.session_state.manager


def init_session_state():
    defaults = {
        "logged_in": False, "user_data": None, "page": "solicitacoes",
        "editing_id": None, "editing_status": None, "confirm_action": None,
        "confirm_return": None, "confirm_approve": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def generate_id():
    import random, string
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=4))


def resolve_role_for_status(user_funcao):
    return ROLE_ALIASES.get(user_funcao, user_funcao)


def compress_image(uploaded_file, max_size=(1024, 1024), quality=70):
    try:
        img = Image.open(uploaded_file)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = base64.b64encode(buf.getvalue()).decode()
        result = f"data:image/jpeg;base64,{data}"
        if len(result) > 1000000:
            return None
        return result
    except Exception:
        return None


def apply_status_color(s):
    if not s:
        return ""
    sl = str(s).lower()
    if "conclu" in sl:
        return "background-color:#27ae60;color:white;"
    if "aprovado final" in sl:
        return "background-color:#2ecc71;color:white;"
    if "aprovad" in sl and "aguardando" not in sl:
        return "background-color:#2980b9;color:white;"
    if "devolvid" in sl or "retorno" in sl:
        return "background-color:#e67e22;color:white;"
    if "em analise" in sl or "aguardando" in sl:
        return "background-color:#f39c12;color:black;"
    if "execucao" in sl:
        return "background-color:#8e44ad;color:white;"
    if "infraestrutura" in sl or "recebido" in sl:
        return "background-color:#16a085;color:white;"
    if "po não executa" in sl or "po nao executa" in sl:
        return "background-color:#e74c3c;color:white;"
    return ""


def fmt_status(s):
    c = apply_status_color(s)
    return f'<span style="{c} padding:2px 8px;border-radius:4px;font-size:12px;">{s}</span>' if c else s


def display_photos(foto_data):
    if not foto_data:
        return
    fotos = str(foto_data).split('|')
    fotos_validas = [f for f in fotos if f.startswith("data:image") or f.startswith("http")]
    if not fotos_validas:
        return
    if len(fotos_validas) == 1:
        st.image(fotos_validas[0], width=300)
    else:
        cols = st.columns(min(len(fotos_validas), 3))
        for i, f in enumerate(fotos_validas[:3]):
            with cols[i]:
                st.image(f, width=250)


def get_flow(om):
    return CONFIG_OMS.get(resolve_om(om), {}).get("flow", [])


def can_approve(user_funcao, status, flow):
    if not flow:
        return False
    resolved = resolve_role_for_status(user_funcao)
    if resolved not in flow:
        return False
    idx = flow.index(resolved)
    expected = f"Aguardando {resolved}"
    if idx == 0:
        return status == expected or ("Devolvido" in status)
    return status == expected


def is_fisc_adm_turn(row_status, flow):
    return (row_status == f"Aguardando {FUNCAO_FISC_ADM_BASE}"
            and FUNCAO_FISC_ADM_BASE in flow)


def is_po_nao_executa_turn(row_status):
    return row_status == TAG_PO_NAO_EXECUTA


def get_next_target(user_funcao, flow):
    if not flow:
        return None, None
    resolved = resolve_role_for_status(user_funcao)
    if resolved not in flow:
        return None, None
    idx = flow.index(resolved)
    if idx >= len(flow) - 1:
        return "Aprovado Final", None
    nxt = flow[idx + 1]
    if nxt == "Aprovado Final":
        return "Aprovado Final", None
    return f"Aguardando {nxt}", nxt


def get_return_targets(user_funcao, flow):
    if not flow:
        return []
    resolved = resolve_role_for_status(user_funcao)
    if resolved not in flow:
        return []
    idx = flow.index(resolved)
    targets = []
    for i in range(idx):
        if i == 0:
            targets.append((flow[i], "Devolvido p/ Correção"))
        else:
            targets.append((flow[i], f"Aguardando {flow[i]}"))
    return targets


def show_detalhamento(demanda_id, manager_instance=None, editable=False):
    st.markdown(f"#### 📋 Detalhamento - {demanda_id}")
    mgr = manager_instance or manager
    if not mgr or not mgr.is_connected:
        st.info("Sistema offline.")
        return
    itens = mgr.get_detalhamento(demanda_id) or []
    if itens:
        df = pd.DataFrame([{
            "Código": i.get("codigo", ""),
            "Descrição": i.get("especificacao", i.get("descricao", "")),
            "Unidade": i.get("unidade", ""),
            "Qtd": i.get("quantidade", 1),
            "Unit. (R$)": i.get("preco_unitario", i.get("preco_sem", 0)),
            "Total (R$)": i.get("quantidade", 1) * i.get("preco_unitario", i.get("preco_sem", 0)),
        } for i in itens])
        st.dataframe(df, use_container_width=True)
        total = df["Total (R$)"].sum()
        st.metric("Total Geral", f"R$ {total:,.2f}")
    else:
        st.info("Nenhum item detalhado para esta demanda.")
    st.session_state[f"show_det_{demanda_id}"] = True


st.set_page_config(page_title="Sistema de Solicitação de Serviços", page_icon="🔧", layout="wide")

st.markdown("""<style>
    .stApp {background-color:#0d1f14;}
    .stSidebar {background-color:#143324;}
    h1,h2,h3,h4,h5,h6 {color:#f5f6fa!important;}
    .stMarkdown {color:#f5f6fa;}
    div[data-testid="stForm"] {border:1px solid #1b5e20;border-radius:8px;padding:10px;}
    .stButton>button {background-color:#1b5e20;color:white;border-radius:6px;border:none;padding:6px 16px;font-weight:bold;}
    .stButton>button:hover {background-color:#2e7d32;}
    div[data-testid="stMetric"] {background-color:#143324;padding:12px;border-radius:8px;border:1px solid #1b5e20;}
    .block-container {padding-top:3rem;}
    section[data-testid="stSidebar"] .stButton>button {background-color:#1b5e20;color:white;}
    section[data-testid="stSidebar"] .stButton>button:hover {background-color:#2e7d32;}
</style>""", unsafe_allow_html=True)

init_session_state()
manager = get_manager()

if not st.session_state.logged_in:
    tab_login, tab_cadastro = st.tabs(["Login", "Cadastro"])

    with tab_login:
        st.markdown("### 🔐 Acessar Sistema")
        with st.form("login_form"):
            identidade = st.text_input("Identidade (matrícula)")
            senha = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", use_container_width=True):
                if not identidade or not senha:
                    st.error("Preencha identidade e senha.")
                elif not manager or not manager.is_connected:
                    st.error("Sistema offline.")
                else:
                    users = manager.get_users()
                    id_clean = str(identidade).strip().lstrip("0")
                    found = next((u for u in users if str(u.get("Identidade", "")).strip().lstrip("0") == id_clean), None)
                    if not found:
                        st.error("Usuário não encontrado.")
                    elif found.get("Status") == "Inativo":
                        st.error("Usuário inativo.")
                    elif verificar_senha(senha, found.get("Senha", "")):
                        st.session_state.logged_in = True
                        st.session_state.user_data = found
                        st.rerun()
                    else:
                        st.error("Senha incorreta.")

    with tab_cadastro:
        st.markdown("### 📝 Cadastrar Novo Usuário")
        om_opts = ["Selecione a OM..."] + list(CONFIG_OMS.keys())
        om_cad = st.selectbox("Organização Militar", om_opts, key="cad_om")
        funcao_opts = CONFIG_OMS.get(om_cad, {}).get("roles", ["Selecione a Função..."]) if om_cad != "Selecione a OM..." else ["Selecione a Função..."]
        funcao_cad = st.selectbox("Função", funcao_opts, key="cad_funcao")
        with st.form("cadastro_form"):
            nome = st.text_input("Nome completo")
            cid = st.text_input("Identidade (matrícula)")
            s1 = st.text_input("Senha", type="password")
            s2 = st.text_input("Confirmar senha", type="password")
            if st.form_submit_button("Cadastrar", use_container_width=True):
                if not all([om_cad != "Selecione a OM...", funcao_cad != "Selecione a Função...", nome, cid, s1]):
                    st.error("Preencha todos os campos.")
                elif s1 != s2:
                    st.error("Senhas não conferem.")
                elif len(s1) < 6:
                    st.error("Senha deve ter pelo menos 6 caracteres.")
                elif not manager or not manager.is_connected:
                    st.error("Sistema offline.")
                else:
                    ok, msg = manager.add_user(resolve_om(om_cad), nome, cid, resolve_role(funcao_cad), s1)
                    st.success(msg) if ok else st.error(msg)

else:
    user = st.session_state.user_data
    u_funcao = user.get("Funcao", "")
    u_om = user.get("OM", "")
    u_nome = user.get("Nome", "")
    u_ident = user.get("Identidade", "")
    pode_criar = u_funcao in ROLES_PODEM_CRIAR_SOLICITACAO
    is_admin = u_funcao == "Administrador da OM"

    with st.sidebar:
        avatar_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "image copy.png")
        if os.path.exists(avatar_path):
            st.image(avatar_path, width=100)
        st.markdown(f"### 👤 {u_nome}")
        st.caption(f"**Função:** {u_funcao}  \n**OM:** {u_om}")
        st.markdown("---")
        if st.button("🏠 Início", use_container_width=True, key="b_inicio"):
            st.session_state.page = "solicitacoes"
            st.session_state.editing_id = None
            st.session_state.editing_status = None
            st.rerun()
        if pode_criar and st.button("➕ Nova Solicitação", use_container_width=True, key="b_nova"):
            st.session_state.page = "nova_solicitacao"
            st.session_state.editing_id = None
            st.session_state.editing_status = None
            st.rerun()
        if u_funcao in ROLES_COM_APROVACOES:
            if st.button("📊 Painel de Aprovações", use_container_width=True, key="b_aprov"):
                st.session_state.page = "aprovacoes"
                st.rerun()
        if st.button("📋 Fluxograma", use_container_width=True, key="b_fluxo"):
            st.session_state.page = "fluxograma"
            st.rerun()
        if is_admin and st.button("👥 Gerenciar Usuários", use_container_width=True, key="b_users"):
            st.session_state.page = "usuarios"
            st.rerun()
        st.markdown("---")
        if st.button("🚪 Sair", use_container_width=True, key="b_sair"):
            st.session_state.logged_in = False
            st.session_state.user_data = None
            st.rerun()

    # ── MINHAS SOLICITAÇÕES ────────────────────────────────────
    if st.session_state.page == "solicitacoes":
        st.markdown("## 📋 Painel de Demandas")
        if not manager or not manager.is_connected:
            st.error("Sistema offline.")
            st.stop()

        data = manager.get_data_from_sheet("Demandas")
        if len(data) <= 1:
            st.info("Nenhuma solicitação encontrada.")
        else:
            rows = data[1:]
            hidden = [h.strip() for h in (user.get("HiddenIDs") or "").split(",") if h.strip()]
            my_reqs = []
            for row in rows:
                rid = row[0] if len(row) > 0 else ""
                if rid in hidden:
                    continue
                r_solic = row[3] if len(row) > 3 else ""
                r_om = row[8] if len(row) > 8 else ""
                r_status = row[2] if len(row) > 2 else ""
                is_mine = r_solic == u_nome and r_om == u_om
                flow = get_flow(r_om)
                in_flow = can_approve(u_funcao, r_status, flow)
                fisc_turn = is_fisc_adm_turn(r_status, flow) and u_funcao == FUNCAO_FISC_ADM_BASE
                po_nao_turn = is_po_nao_executa_turn(r_status) and u_funcao == FUNCAO_FISC_ADM_BASE
                if is_mine or in_flow or fisc_turn or po_nao_turn:
                    my_reqs.append(row)

            if not my_reqs:
                st.info("Nenhuma solicitação para exibir.")
            else:
                for row in my_reqs:
                    rid = row[0] if len(row) > 0 else ""
                    r_data = row[1] if len(row) > 1 else ""
                    r_status = row[2] if len(row) > 2 else ""
                    r_solic = row[3] if len(row) > 3 else ""
                    r_local = row[4] if len(row) > 4 else ""
                    r_tipo = row[5] if len(row) > 5 else ""
                    r_desc = row[6] if len(row) > 6 else ""
                    r_urg = row[7] if len(row) > 7 else ""
                    r_om = row[8] if len(row) > 8 else ""
                    r_foto = row[10] if len(row) > 10 else ""
                    r_parecer = row[11] if len(row) > 11 else ""
                    r_reg = row[12] if len(row) > 12 else ""

                    desc_exib = descricao_original(r_desc)
                    if "Devolvido" in r_status and r_reg:
                        match = re.findall(r'\[RETORNO [^\]]+\]:\s*(.*)', r_reg)
                        r_status_display = f"{r_status} — {match[-1].strip()}" if match else r_status
                    else:
                        r_status_display = r_status

                    with st.expander(f"**{rid}** | {r_tipo} | {r_local}", expanded=False):
                        c1, c2 = st.columns([2, 1])
                        with c1:
                            st.markdown(f"**Status:** {fmt_status(r_status_display)}", unsafe_allow_html=True)
                            st.markdown(f"**Data:** {r_data}  \n**Solicitante:** {r_solic}  \n**Local:** {r_local}  \n**Tipo:** {r_tipo}  \n**Urgência:** {r_urg}  \n**Descrição:** {desc_exib}")
                            if r_parecer:
                                st.markdown(f"**Parecer PO:** {r_parecer}")
                            if r_foto:
                                display_photos(r_foto)
                        with c2:
                            flow = get_flow(r_om)
                            resolved = resolve_role_for_status(u_funcao)
                            is_owner = r_solic == u_nome and r_om == u_om
                            ok_approve = can_approve(u_funcao, r_status, flow)
                            fisc_turn = is_fisc_adm_turn(r_status, flow) and u_funcao == FUNCAO_FISC_ADM_BASE
                            po_nao_turn = is_po_nao_executa_turn(r_status) and u_funcao == FUNCAO_FISC_ADM_BASE

                            if fisc_turn:
                                if st.button("📤 Enviar p/ PO (Serviços Gerais)", key=f"fpo_{rid}", use_container_width=True):
                                    st.session_state.confirm_approve = ("fisc_to_po", rid, r_om)
                                    st.rerun()

                            elif po_nao_turn:
                                if st.button("🏗️ Enviar p/ Infraestrutura", key=f"fi_{rid}", use_container_width=True):
                                    st.session_state.confirm_approve = ("fisc_to_infra", rid, r_om)
                                    st.rerun()

                            elif ok_approve:
                                nxt_status, nxt_role = get_next_target(u_funcao, flow)
                                if nxt_status:
                                    if nxt_status == "Aprovado Final":
                                        if st.button("✅ Aprovar Final", key=f"af_{rid}", use_container_width=True):
                                            st.session_state.confirm_approve = ("approve_final", rid, r_om)
                                            st.rerun()
                                    else:
                                        if st.button(f"✅ Enviar p/ {nxt_role}", key=f"ap_{rid}", use_container_width=True):
                                            st.session_state.confirm_approve = ("approve_next", rid, r_om)
                                            st.rerun()

                                if is_owner and ("Devolvido" in r_status or r_status == f"Aguardando {resolved}"):
                                    if st.button("✏️ Editar", key=f"ed_{rid}", use_container_width=True):
                                        st.session_state.editing_id = rid
                                        st.session_state.editing_status = r_status
                                        st.session_state.page = "nova_solicitacao"
                                        st.rerun()

                                ret_opts = get_return_targets(u_funcao, flow)
                                if ret_opts:
                                    with st.popover("↩️ Devolver"):
                                        st.markdown("**Devolver para:**")
                                        destino = st.selectbox("Destino", [o[1] for o in ret_opts], key=f"ret_dst_{rid}")
                                        tipo_ret = st.radio("Tipo", ["Para Correção", "Para Exclusão"], key=f"ret_tipo_{rid}")
                                        motivo = st.text_area("Motivo", key=f"ret_mot_{rid}", height=80)
                                        if st.button("Confirmar Devolução", key=f"ret_ok_{rid}"):
                                            if not motivo:
                                                st.error("Informe o motivo.")
                                            else:
                                                idx_sel = [o[1] for o in ret_opts].index(destino)
                                                target_role = ret_opts[idx_sel][0]
                                                if idx_sel == 0:
                                                    novo_status = "Devolvido p/ Correção" if tipo_ret == "Para Correção" else "Devolvido p/ Exclusão"
                                                else:
                                                    novo_status = f"Aguardando {target_role}"
                                                tipo_tag = "CORREÇÃO" if "Correção" in tipo_ret else "EXCLUSÃO"
                                                ok, m = manager.update_status(rid, novo_status, f"({tipo_tag}) {motivo}", u_nome, "RETORNO")
                                                st.success(m) if ok else st.error(m)
                                                time.sleep(0.5)
                                                st.rerun()

                                if is_owner or ok_approve or fisc_turn or po_nao_turn:
                                    if st.button("🗑️ Excluir", key=f"dl_{rid}", use_container_width=True):
                                        st.session_state.confirm_action = ("delete", rid)

                            if st.button("📋 Detalhar", key=f"dt_{rid}", use_container_width=True):
                                st.session_state[f"show_det_{rid}"] = not st.session_state.get(f"show_det_{rid}", False)

                        if st.session_state.get(f"show_det_{rid}"):
                            show_detalhamento(rid)

                        if r_reg:
                            st.markdown("---")
                            st.markdown("**Registro:**")
                            for line in str(r_reg).split("\n"):
                                if line.strip():
                                    st.text(line.strip())

        if st.session_state.confirm_approve:
            act, act_id, act_om = st.session_state.confirm_approve
            act_flow = get_flow(act_om)
            with st.expander(f"⚠️ Confirmar ação em {act_id}", expanded=True):
                if act == "fisc_to_po":
                    st.warning("Encaminhar demanda para Análise do PO (Serviços Gerais)?")
                elif act == "fisc_to_infra":
                    st.warning("Encaminhar demanda para a Seção de Infraestrutura?")
                elif act == "approve_final":
                    st.warning("Aprovar esta demanda definitivamente?")
                elif act == "approve_next":
                    nxt_status, nxt_role = get_next_target(u_funcao, act_flow)
                    st.warning(f"Encaminhar demanda para {nxt_role}?")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Confirmar", key="confirm_ap", type="primary"):
                        if act == "fisc_to_po":
                            ok, m = manager.update_status(act_id, STATUS_ANALISE_SERVICOS_GERAIS, f"Encaminhado p/ PO (Serviços Gerais) por {u_nome}", u_nome, "APROVADO")
                        elif act == "fisc_to_infra":
                            ok, m = manager.update_status(act_id, STATUS_ANALISE_INFRAESTRUTURA, f"Encaminhado p/ Infraestrutura por {u_nome}", u_nome, "APROVADO")
                        elif act == "approve_final":
                            ok, m = manager.update_status(act_id, "Aprovado Final", f"Aprovado por {u_nome}", u_nome)
                        elif act == "approve_next":
                            nxt_status, _ = get_next_target(u_funcao, act_flow)
                            ok, m = manager.update_status(act_id, nxt_status, f"Encaminhado por {u_nome}", u_nome, "APROVADO")
                        st.success(m) if ok else st.error(m)
                        st.session_state.confirm_approve = None
                        time.sleep(0.5)
                        st.rerun()
                with c2:
                    if st.button("Cancelar", key="cancel_ap"):
                        st.session_state.confirm_approve = None
                        st.rerun()

        if st.session_state.confirm_action:
            act, act_id = st.session_state.confirm_action
            if act == "delete":
                with st.expander(f"⚠️ Confirmar exclusão de {act_id}", expanded=True):
                    st.warning("Tem certeza que deseja excluir esta solicitação?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Sim, Excluir", key="confirm_del", type="primary"):
                            ok, m = manager.delete_solicitacao(act_id)
                            st.success(m) if ok else st.error(m)
                            st.session_state.confirm_action = None
                            time.sleep(0.5)
                            st.rerun()
                    with c2:
                        if st.button("Cancelar", key="cancel_del"):
                            st.session_state.confirm_action = None
                            st.rerun()

    # ── NOVA SOLICITAÇÃO / EDITAR ──────────────────────────────
    elif st.session_state.page == "nova_solicitacao":
        eid = st.session_state.editing_id
        st.markdown(f"## {'✏️ Editar' if eid else '➕ Nova'} Solicitação")

        data = manager.get_data_from_sheet("Demandas") if manager and manager.is_connected else []
        ext = None
        if eid and len(data) > 1:
            ext = next((r for r in data[1:] if r[0] == eid), None)

        edit_status = st.session_state.editing_status
        if not edit_status and ext:
            edit_status = ext[2] if len(ext) > 2 else None

        with st.form("solicitacao_form"):
            local = st.text_input("Local*", value=ext[4] if ext else "", placeholder="Local da Instalação")
            ti = TIPOS_ORIGINAIS.index(ext[5]) + 1 if ext and ext[5] in TIPOS_ORIGINAIS else 0
            tipo = st.selectbox("Tipo*", ["Selecione..."] + TIPOS_ORIGINAIS, index=ti)
            ui = URGENCIAS_ORIGINAIS.index(ext[7]) + 1 if ext and ext[7] in URGENCIAS_ORIGINAIS else 0
            urg = st.selectbox("Urgência*", ["Selecione..."] + URGENCIAS_ORIGINAIS, index=ui)
            desc = st.text_area("Descrição*", value=ext[6] if ext else "", height=120, placeholder="Descreva o problema detalhadamente...")
            fotos = st.file_uploader("📎 Anexar Fotos (Máx 3 - 5MB cada)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="fotos_up")
            if fotos and len(fotos) > 3:
                st.warning("Máximo 3 fotos. Apenas as 3 primeiras serão usadas.")
                fotos = fotos[:3]
            if st.form_submit_button("Enviar Solicitação" if not eid else "Atualizar", use_container_width=True):
                if not local or tipo == "Selecione..." or urg == "Selecione..." or not desc:
                    st.error("Preencha todos os campos obrigatórios (*).")
                else:
                    fotos_b64 = []
                    for f in (fotos or [])[:3]:
                        enc = compress_image(f)
                        if enc:
                            fotos_b64.append(enc)
                        else:
                            st.warning(f"Foto não processada (muito grande ou erro): {f.name}")
                    foto_final = "|".join(fotos_b64)
                    if eid and ext and not fotos_b64:
                        foto_final = ext[10] if len(ext) > 10 else ""
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if eid:
                        salvar_status = edit_status if edit_status else (ext[2] if len(ext) > 2 else "Em Aberto")
                        ok, m = manager.update_solicitacao(eid, [now, salvar_status, u_nome, local, tipo, desc, urg, u_om, foto_final])
                    else:
                        flow = get_flow(u_om)
                        status_inicial = f"Aguardando {flow[0]}" if flow else "Em Aberto"
                        new_id = generate_id()
                        ok, m = manager.add_solicitacao([new_id, now, status_inicial, u_nome, local, tipo, desc, urg, u_om, foto_final])
                    st.success(m) if ok else st.error(m)
                    st.session_state.page = "solicitacoes"
                    st.session_state.editing_id = None
                    st.session_state.editing_status = None
                    time.sleep(0.5)
                    st.rerun()

        if st.button("Cancelar"):
            st.session_state.page = "solicitacoes"
            st.session_state.editing_id = None
            st.session_state.editing_status = None
            st.rerun()

    # ── PAINEL DE APROVAÇÕES ───────────────────────────────────
    elif st.session_state.page == "aprovacoes":
        st.markdown("## 📊 Painel de Aprovações")
        if not manager or not manager.is_connected:
            st.error("Sistema offline.")
            st.stop()

        blocks_visiveis = []
        if u_funcao == FUNCAO_FISC_ADM_BASE or is_admin:
            blocks_visiveis = list(APROVACOES_BLOCOS.keys())
        elif u_funcao == FUNCAO_SECAO_SERVICOS_GERAIS:
            blocks_visiveis = ["Aprovados_Servicos_Gerais"]
        elif u_funcao == "Chefe da Seção de Infraestrutura":
            blocks_visiveis = ["Aprovados_Infraestrutura"]

        if not blocks_visiveis:
            st.info("Você não tem acesso a nenhum bloco de aprovações.")
            st.stop()

        tabs = st.tabs([APROVACOES_BLOCOS[b] for b in blocks_visiveis])

        for i, blk in enumerate(blocks_visiveis):
            with tabs[i]:
                data = manager.get_aproved_data(blk)
                if len(data) <= 1:
                    st.info("Nenhuma demanda nesta fila.")
                    continue

                for row in data[1:]:
                    rid = row[0] if len(row) > 0 else ""
                    r_status = row[2] if len(row) > 2 else ""
                    r_solic = row[3] if len(row) > 3 else ""
                    r_local = row[4] if len(row) > 4 else ""
                    r_tipo = row[5] if len(row) > 5 else ""
                    r_desc = row[6] if len(row) > 6 else ""
                    r_urg = row[7] if len(row) > 7 else ""
                    r_foto = row[10] if len(row) > 10 else ""
                    r_parecer = row[11] if len(row) > 11 else ""
                    r_reg = row[12] if len(row) > 12 else ""
                    r_om = row[8] if len(row) > 8 else ""

                    with st.expander(f"**{rid}** | {r_tipo} | {r_local}", expanded=False):
                        st.markdown(f"**Status:** {fmt_status(r_status)}", unsafe_allow_html=True)
                        st.markdown(f"**Solicitante:** {r_solic}  \n**Urgência:** {r_urg}  \n**Descrição:** {descricao_original(r_desc)}")
                        if r_parecer:
                            st.markdown(f"**Parecer PO:** {r_parecer}")
                        if r_foto:
                            display_photos(r_foto)

                        btns = st.columns(4)
                        with btns[0]:
                            if st.button("🗑️", key=f"dl_ap_{blk}_{rid}", help="Ocultar da minha lista"):
                                ok, m = manager.hide_solicitacao_for_user(u_ident, rid)
                                st.success(m) if ok else st.error(m)
                                time.sleep(0.5)
                                st.rerun()
                        with btns[1]:
                            if st.button("📋", key=f"dt_ap_{blk}_{rid}", help="Detalhar"):
                                st.session_state[f"show_det_{rid}"] = not st.session_state.get(f"show_det_{rid}", False)

                        if u_funcao == FUNCAO_SECAO_SERVICOS_GERAIS and r_status == STATUS_ANALISE_SERVICOS_GERAIS:
                            e, n = st.columns(2)
                            with e:
                                if st.button("✅ Executar", key=f"ex_{rid}", use_container_width=True):
                                    ok, m = manager.parecer_servicos_gerais_para_fisc_adm(rid, TAG_PO_EXECUTA, u_nome)
                                    st.success(m) if ok else st.error(m)
                                    time.sleep(0.5)
                                    st.rerun()
                            with n:
                                if st.button("🚫 Não Executar", key=f"ne_{rid}", use_container_width=True):
                                    ok, m = manager.parecer_servicos_gerais_para_fisc_adm(rid, TAG_PO_NAO_EXECUTA, u_nome)
                                    st.success(m) if ok else st.error(m)
                                    time.sleep(0.5)
                                    st.rerun()

                        if u_funcao == FUNCAO_SECAO_SERVICOS_GERAIS and r_status == STATUS_EM_EXECUCAO_PO:
                            if st.button("✅ Concluir Serviço", key=f"cp_{rid}", use_container_width=True):
                                ok, m = manager.concluir_servico_po(rid, u_nome)
                                st.success(m) if ok else st.error(m)
                                time.sleep(0.5)
                                st.rerun()

                        if u_funcao == "Chefe da Seção de Infraestrutura":
                            if r_status == STATUS_ANALISE_INFRAESTRUTURA:
                                if st.button("👁️ Ciente", key=f"ci_{rid}", use_container_width=True):
                                    ok, m = manager.update_status(rid, STATUS_RECEBIDO_INFRAESTRUTURA, f"Ciente por {u_nome}", u_nome, "APROVADO")
                                    st.success(m) if ok else st.error(m)
                                    time.sleep(0.5)
                                    st.rerun()
                            if r_status == STATUS_RECEBIDO_INFRAESTRUTURA:
                                if st.button("✅ Concluir (Infra)", key=f"ci_infra_{rid}", use_container_width=True):
                                    ok, m = manager.concluir_servico_infraestrutura(rid, u_nome)
                                    st.success(m) if ok else st.error(m)
                                    time.sleep(0.5)
                                    st.rerun()

                        if u_funcao == FUNCAO_FISC_ADM_BASE:
                            if r_status == TAG_PO_NAO_EXECUTA:
                                if st.button("🏗️ Enviar p/ Infraestrutura", key=f"fai_{rid}", use_container_width=True):
                                    ok, m = manager.update_status(rid, STATUS_ANALISE_INFRAESTRUTURA, f"Encaminhado p/ Infraestrutura por {u_nome}", u_nome, "APROVADO")
                                    st.success(m) if ok else st.error(m)
                                    time.sleep(0.5)
                                    st.rerun()

                        if st.session_state.get(f"show_det_{rid}"):
                            show_detalhamento(rid)

                        if r_reg:
                            st.markdown("---")
                            st.markdown("**Registro:**")
                            for line in str(r_reg).split("\n"):
                                if line.strip():
                                    st.text(line.strip())

    # ── FLUXOGRAMA ─────────────────────────────────────────────
    elif st.session_state.page == "fluxograma":
        st.markdown("## 📋 Fluxograma da Demanda")
        if not manager or not manager.is_connected:
            st.error("Sistema offline.")
            st.stop()

        data = manager.get_data_from_sheet("Demandas")
        if len(data) <= 1:
            st.info("Nenhuma demanda encontrada.")
            st.stop()

        options = ["-- Selecione uma demanda --"]
        row_map = {}
        for row in data[1:]:
            rid = row[0] if len(row) > 0 else ""
            r_status = row[2] if len(row) > 2 else ""
            r_local = row[4] if len(row) > 4 else ""
            r_tipo = row[5] if len(row) > 5 else ""
            r_desc = row[6] if len(row) > 6 else ""
            r_om = row[8] if len(row) > 8 else ""
            desc_short = r_desc[:60] if r_desc else "Sem descrição"
            label = f"#{rid} - {r_local}/{r_tipo} [{r_status}]"
            options.append(label)
            row_map[label] = row

        sel = st.selectbox("Selecione a demanda:", options, key="fluxo_sel")

        if sel != "-- Selecione uma demanda --":
            row = row_map[sel]
            rid = row[0] if len(row) > 0 else ""
            r_status = row[2] if len(row) > 2 else ""
            r_om = row[8] if len(row) > 8 else ""
            r_local = row[4] if len(row) > 4 else ""
            r_tipo = row[5] if len(row) > 5 else ""
            r_reg = row[12] if len(row) > 12 else ""
            r_parecer = row[11] if len(row) > 11 else ""

            st.caption(f"📌 {r_local}/{r_tipo} | Demanda #{rid} | OM: {r_om} | {r_status}")

            flow = get_flow(r_om)
            if not flow:
                st.warning("Fluxo não configurado para esta OM.")
            else:
                approved_roles = set()
                returner_roles = set()
                for line in str(r_reg).split('\n'):
                    m = re.match(r'\[APROVADO\s+([^\]]+)\]', line)
                    if m:
                        approved_roles.add(m.group(1).strip())
                    m = re.match(r'\[RETORNO\s+([^\]]+)\]', line)
                    if m:
                        returner_roles.add(m.group(1).strip())

                is_final = r_status == "Aprovado Final" or r_status.startswith("Aprovado - ")
                is_devolvido = "Devolvido" in r_status
                current_role = None
                if "Aguardando" in r_status:
                    current_role = r_status.replace("Aguardando ", "").strip()
                elif is_devolvido:
                    current_role = flow[0] if flow else None

                parecer = extrair_parecer_po(r_parecer, row[6] if len(row) > 6 else "")
                is_po_flow = r_status in (STATUS_ANALISE_SERVICOS_GERAIS, STATUS_EM_EXECUCAO_PO, STATUS_CONCLUIDO_PO)
                is_infra_flow = r_status in (STATUS_ANALISE_INFRAESTRUTURA, STATUS_RECEBIDO_INFRAESTRUTURA, STATUS_CONCLUIDO_INFRA)
                is_po_nao = r_status == TAG_PO_NAO_EXECUTA

                nodes = []
                for role in flow:
                    if role == "Aprovado Final":
                        continue
                    if role == current_role:
                        sub = r_status
                        if is_devolvido:
                            sub = "↩️ Devolvido"
                        nodes.append((role, "current", sub))
                    elif role in approved_roles:
                        sub = "↩️ Devolveu" if role in returner_roles else "✅ Aprovou"
                        nodes.append((role, "done", sub))
                    else:
                        nodes.append((role, "pending", ""))

                if is_po_flow or is_po_nao:
                    st.markdown("---")
                    st.markdown("**Ramificação PO / Infraestrutura:**")
                    po_state = "current" if r_status == STATUS_ANALISE_SERVICOS_GERAIS else "done"
                    nodes.append(("PO (Serviços Gerais)", po_state, r_status if po_state == "current" else "Análise concluída"))

                    if r_status == STATUS_EM_EXECUCAO_PO:
                        nodes.append(("PO — Executando", "current", r_status))
                    elif r_status == STATUS_CONCLUIDO_PO:
                        nodes.append(("PO — Executando", "done", "Concluído"))

                    if is_po_nao:
                        nodes.append(("PO NÃO EXECUTA", "current", "Retornou ao Fisc Adm"))

                    if is_po_nao or is_infra_flow:
                        fisc_st = "done" if (is_infra_flow or is_po_nao) else "pending"
                        nodes.append(("Fisc Adm Base", fisc_st, "Reencaminhou p/ Infraestrutura"))

                    if is_infra_flow:
                        if r_status == STATUS_ANALISE_INFRAESTRUTURA:
                            nodes.append(("Infraestrutura", "current", "⚠️ Aguardando ciência"))
                        elif r_status == STATUS_RECEBIDO_INFRAESTRUTURA:
                            nodes.append(("Infraestrutura", "done", "Recebido"))
                        elif r_status == STATUS_CONCLUIDO_INFRA:
                            nodes.append(("Infraestrutura", "done", "Concluído"))

                if is_final:
                    nodes.append(("Aprovado Final", "done", r_status))

                st.markdown("---")
                for label, state, sub in nodes:
                    if state == "current":
                        st.markdown(f"🔴 **{label}** — {sub}")
                    elif state == "done":
                        st.markdown(f"✅ ~~{label}~~ — {sub}")
                    else:
                        st.markdown(f"⬜ {label}")

    # ── GERENCIAR USUÁRIOS ─────────────────────────────────────
    elif st.session_state.page == "usuarios":
        if not is_admin:
            st.error("Acesso restrito a Administradores.")
            st.stop()
        st.markdown("## 👥 Gerenciar Usuários")
        if not manager or not manager.is_connected:
            st.error("Sistema offline.")
            st.stop()

        users = manager.get_users()
        om_users = [u for u in users if u.get("OM") == u_om]

        if not om_users:
            st.info("Nenhum usuário cadastrado para sua OM.")
        else:
            for u in om_users:
                un = u.get("Nome", "")
                ui2 = u.get("Identidade", "")
                uf = u.get("Funcao", "")
                us = u.get("Status", "")
                with st.expander(f"👤 {un} | {uf} | {us}", expanded=False):
                    st.markdown(f"**Identidade:** {ui2}  \n**OM:** {u.get('OM', '')}  \n**Status:** {us}")
                    if str(ui2).strip().lstrip("0") != str(u_ident).strip().lstrip("0"):
                        if st.button(f"🗑️ Excluir {un}", key=f"du_{ui2}"):
                            ok, m = manager.delete_user(ui2)
                            st.success(m) if ok else st.error(m)
                            time.sleep(0.5)
                            st.rerun()

        st.markdown("---")
        st.markdown("### ➕ Cadastrar Novo Usuário")
        om_adm = st.selectbox("OM", ["Selecione a OM..."] + list(CONFIG_OMS.keys()), key="adm_om")
        fa_opts = CONFIG_OMS.get(om_adm, {}).get("roles", ["Selecione..."]) if om_adm != "Selecione a OM..." else ["Selecione..."]
        fa_adm = st.selectbox("Função", fa_opts, key="adm_fa")
        with st.form("adm_form"):
            nm = st.text_input("Nome completo")
            id2 = st.text_input("Identidade")
            sw = st.text_input("Senha", type="password")
            if st.form_submit_button("Cadastrar", use_container_width=True):
                if not all([om_adm != "Selecione a OM...", fa_adm != "Selecione...", nm, id2, sw]):
                    st.error("Preencha todos os campos.")
                elif len(sw) < 6:
                    st.error("Senha deve ter pelo menos 6 caracteres.")
                else:
                    ok, m = manager.add_user(resolve_om(om_adm), nm, id2, resolve_role(fa_adm), sw)
                    st.success(m) if ok else st.error(m)
                    time.sleep(0.5)
                    st.rerun()
