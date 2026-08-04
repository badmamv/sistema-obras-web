from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = None

HEADER_DEMANDA = [
    "ID", "Data", "Status", "Solicitante", "Local", "Tipo", "Descricao",
    "Urgencia", "OM", "Prioridade", "FotoURL", "ParecerPO", "Registro",
]

COL_MAP_DEMANDA = {
    "ID": "id",
    "Data": "data",
    "Status": "status",
    "Solicitante": "solicitante",
    "Local": "local",
    "Tipo": "tipo",
    "Descricao": "descricao",
    "Urgencia": "urgencia",
    "OM": "om",
    "Prioridade": "prioridade",
    "FotoURL": "fotourl",
    "ParecerPO": "parecerpo",
    "Registro": "registro",
}

COL_MAP_USUARIO = {
    "OM": "om",
    "Nome": "nome",
    "Identidade": "identidade",
    "Funcao": "funcao",
    "Senha": "senha",
    "Status": "status",
    "HiddenIDs": "hidden_ids",
}

DEMANDA_DB_TO_APP = {v: k for k, v in COL_MAP_DEMANDA.items()}
USUARIO_DB_TO_APP = {v: k for k, v in COL_MAP_USUARIO.items()}


def _demanda_db_to_app(row: dict) -> dict:
    out = {}
    for db_key, value in row.items():
        app_key = DEMANDA_DB_TO_APP.get(db_key, db_key)
        out[app_key] = value if value is not None else ""
    for k in ("ID", "Data", "Status", "Solicitante", "Local", "Tipo",
              "Descricao", "Urgencia", "OM", "Prioridade", "FotoURL",
              "ParecerPO", "Registro"):
        out.setdefault(k, "")
    return out


def _usuario_db_to_app(row: dict) -> dict:
    out = {}
    for db_key, value in row.items():
        app_key = USUARIO_DB_TO_APP.get(db_key, db_key)
        out[app_key] = value if value is not None else ""
    for k in ("OM", "Nome", "Identidade", "Funcao", "Senha", "Status", "HiddenIDs"):
        out.setdefault(k, "")
    return out


def _demanda_app_to_db(data: dict) -> dict:
    out = {}
    for app_key, value in data.items():
        db_key = COL_MAP_DEMANDA.get(app_key, app_key)
        out[db_key] = value
    return out


def _demanda_row_to_list(d: dict) -> list:
    return [d.get(h, "") for h in HEADER_DEMANDA]


class SupabaseManager:

    def __init__(self, supabase_url: str = "", supabase_key: str = "",
                 poll_interval_ms: int = 3000):
        self._client: Client | None = None
        self._connected = False
        self._supabase_url = supabase_url
        self._supabase_key = supabase_key
        self._poll_interval_ms = poll_interval_ms

        if supabase_url and supabase_key and create_client is not None:
            try:
                self._client = create_client(supabase_url, supabase_key)
                self._connected = True
            except Exception as e:
                print(f"[SupabaseManager] Erro ao conectar: {e}")

    @property
    def client(self) -> Client | None:
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    def connect(self):
        if self.is_connected:
            return True, "Conexao Supabase Ativa."
        if not create_client:
            return False, "Pacote 'supabase' nao instalado. Execute: pip install supabase"
        if not self._supabase_url or not self._supabase_key:
            return False, "URL ou chave do Supabase nao configurados."
        try:
            self._client = create_client(self._supabase_url, self._supabase_key)
            self._connected = True
            return True, "Conectado ao Supabase com sucesso."
        except Exception as e:
            self._connected = False
            return False, f"Erro ao conectar ao Supabase: {e}"

    def _table(self, name: str):
        if not self.is_connected:
            raise RuntimeError("Supabase nao esta conectado.")
        return self._client.table(name)

    def _execute(self, query):
        try:
            result = query.execute()
            return result.data if hasattr(result, "data") else result
        except Exception as e:
            raise RuntimeError(f"Erro na operacao Supabase: {e}")

    def get_users(self):
        if not self.is_connected:
            return []
        try:
            data = self._execute(self._table("usuarios").select("*"))
            return [_usuario_db_to_app(row) for row in data]
        except Exception as e:
            print(f"[SupabaseManager] Erro ao buscar usuarios: {e}")
            return []

    def add_user(self, om: str, nome: str, identidade: str,
                 funcao: str, senha: str):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            identidade = str(identidade).strip().lstrip("0")

            existing = self._execute(
                self._table("usuarios").select("*")
                .eq("identidade", identidade)
            )
            if existing:
                return False, "Esta identidade ja esta cadastrada."

            existing_all = self._execute(self._table("usuarios").select("*"))
            for u in existing_all:
                uf = u.get("funcao", "")
                uo = u.get("om", "")
                unome = u.get("nome", "")
                if funcao == "Fisc Adm Base" and uf == funcao:
                    return False, f"Ja existe um Fisc Adm Base cadastrado no sistema ({unome} na {uo})."
                if funcao == "Chefe da Secao de Infraestrutura" and uf == funcao:
                    return False, f"Ja existe um Chefe da Secao de Infraestrutura cadastrado no sistema ({unome} na {uo})."
                if funcao == "Secao de Servicos Gerais" and uf == funcao:
                    return False, f"Ja existe um usuario da Secao de Servicos Gerais cadastrado no sistema ({unome} na {uo})."
                if funcao != "Outros" and uf == funcao and uo == om:
                    return False, f"Ja existe um {funcao} cadastrado para a {om}."

            import hashlib
            senha_hash = hashlib.sha256(senha.encode("utf-8")).hexdigest()

            self._execute(
                self._table("usuarios").insert({
                    "om": om,
                    "nome": nome,
                    "identidade": identidade,
                    "funcao": funcao,
                    "senha": senha_hash,
                    "status": "Ativo",
                    "hidden_ids": "",
                })
            )
            return True, "Usuario cadastrado com sucesso."
        except Exception as e:
            return False, f"Erro ao cadastrar: {e}"

    def delete_user(self, identidade: str):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            identidade = str(identidade).strip().lstrip("0")
            self._execute(
                self._table("usuarios").delete()
                .eq("identidade", identidade)
            )
            return True, "Usuario excluido com sucesso."
        except Exception as e:
            return False, str(e)

    def add_solicitacao(self, data_list: list):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            doc_id = str(data_list[0])
            row = {
                "id": doc_id,
                "data": data_list[1],
                "status": data_list[2],
                "solicitante": data_list[3],
                "local": data_list[4],
                "tipo": data_list[5],
                "descricao": data_list[6],
                "urgencia": data_list[7],
                "om": data_list[8],
                "prioridade": "0",
                "fotourl": data_list[9] if len(data_list) > 9 else "",
                "parecerpo": "",
                "registro": "",
            }
            self._execute(self._table("demandas").insert(row))
            return True, "Solicitacao enviada com sucesso!"
        except Exception as e:
            return False, str(e)

    def get_data_from_sheet(self, sheet_name: str):
        if not self.is_connected:
            return []
        try:
            if "Usuarios" in sheet_name:
                users = self.get_users()
                header = ["OM", "Nome", "Identidade", "Funcao", "Senha", "Status", "HiddenIDs"]
                rows = [[u.get(h, "") for h in header] for u in users]
                return [header] + rows

            data = self._execute(
                self._table("demandas").select("*").order("created_at", desc=True)
            )
            rows = [_demanda_row_to_list(_demanda_db_to_app(row)) for row in data]
            return [HEADER_DEMANDA] + rows
        except Exception as e:
            print(f"[SupabaseManager] Erro get_data_from_sheet: {e}")
            return []

    def update_status(self, id_solicitacao: str, novo_status: str,
                      motivo: str = None, quem: str = None, prefix: str = None):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            update_data = {"status": novo_status}

            if motivo:
                existing = self._execute(
                    self._table("demandas").select("registro")
                    .eq("id", id_solicitacao).limit(1).single()
                )
                if isinstance(existing, list):
                    registro_atual = existing[0].get("registro", "") if existing else ""
                elif isinstance(existing, dict):
                    registro_atual = existing.get("registro", "")
                else:
                    registro_atual = ""

                tag = prefix or ("APROVADO" if str(motivo).startswith("Aprovado") else "RETORNO")
                linha = f"[{tag} {quem}]: {motivo}" if quem else f"[{tag}]: {motivo}"
                novo_registro = f"{registro_atual}\n{linha}".strip() if registro_atual else linha
                update_data["registro"] = novo_registro

            self._execute(
                self._table("demandas").update(update_data).eq("id", id_solicitacao)
            )
            return True, "Status atualizado com sucesso."
        except Exception as e:
            return False, str(e)

    def update_solicitacao(self, id_solicitacao: str, dados: list):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            update_data = {
                "data": dados[0],
                "status": dados[1],
                "solicitante": dados[2],
                "local": dados[3],
                "tipo": dados[4],
                "descricao": dados[5],
                "urgencia": dados[6],
                "om": dados[7],
                "fotourl": dados[8] if len(dados) > 8 else "",
            }
            self._execute(
                self._table("demandas").update(update_data).eq("id", id_solicitacao)
            )
            return True, "Solicitacao atualizada com sucesso!"
        except Exception as e:
            return False, str(e)

    def delete_solicitacao(self, id_solicitacao: str):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            self._execute(
                self._table("demandas").delete().eq("id", id_solicitacao)
            )
            return True, "Solicitacao excluida com sucesso."
        except Exception as e:
            return False, str(e)

    def hide_solicitacao_for_user(self, identidade_usuario: str, ids_solicitacao):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            identidade_usuario = str(identidade_usuario).strip().lstrip("0")

            users = self._execute(
                self._table("usuarios").select("*")
                .eq("identidade", identidade_usuario).limit(1)
            )
            if not users:
                return False, "Usuario nao encontrado."

            user = users[0]
            current_hidden = user.get("hidden_ids", "") or ""
            hidden_list = [sid.strip() for sid in current_hidden.split(",") if sid.strip()]

            if isinstance(ids_solicitacao, list):
                for sid in ids_solicitacao:
                    if str(sid) not in hidden_list:
                        hidden_list.append(str(sid))
            else:
                if str(ids_solicitacao) not in hidden_list:
                    hidden_list.append(str(ids_solicitacao))

            self._execute(
                self._table("usuarios").update({"hidden_ids": ",".join(hidden_list)})
                .eq("identidade", identidade_usuario)
            )
            return True, "Item ocultado com sucesso."
        except Exception as e:
            return False, str(e)

    def move_to_aproved_table(self, id_solicitacao: str, table_name: str):
        from constants import status_para_bloco_aprovacao
        return self.update_status(id_solicitacao, status_para_bloco_aprovacao(table_name))

    def parecer_servicos_gerais_para_fisc_adm(self, id_solicitacao: str,
                                               parecer_tag: str, quem: str):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            from constants import (STATUS_ANALISE_SERVICOS_GERAIS,
                                   status_alvos_bloco_aprovacao,
                                   TAG_PO_EXECUTA, TAG_PO_NAO_EXECUTA,
                                   STATUS_EM_EXECUCAO_PO)

            existing = self._execute(
                self._table("demandas").select("*")
                .eq("id", id_solicitacao).limit(1)
            )
            if not existing:
                return False, "Solicitacao nao encontrada."

            d = existing[0]
            status_atual = d.get("status", "")
            if status_atual != STATUS_ANALISE_SERVICOS_GERAIS:
                status_sg = status_alvos_bloco_aprovacao("Aprovados_Servicos_Gerais")
                if status_atual not in status_sg:
                    return False, "Esta demanda nao esta aguardando analise da Secao de Servicos Gerais."

            if parecer_tag == TAG_PO_EXECUTA:
                novo_status = STATUS_EM_EXECUCAO_PO
            else:
                novo_status = TAG_PO_NAO_EXECUTA

            registro_atual = d.get("registro", "") or ""
            linha = f"[APROVADO {quem}]: Parecer {parecer_tag}"
            novo_registro = f"{registro_atual}\n{linha}".strip() if registro_atual else linha

            self._execute(
                self._table("demandas").update({
                    "status": novo_status,
                    "parecerpo": parecer_tag,
                    "registro": novo_registro,
                }).eq("id", id_solicitacao)
            )

            if parecer_tag == TAG_PO_EXECUTA:
                return True, "Parecer registrado. A demanda esta no seu Painel de Aprovacoes para acompanhamento da execucao."
            else:
                return True, "Parecer registrado. A demanda foi devolvida ao Fisc Adm para encaminhamento."
        except Exception as e:
            return False, str(e)

    def concluir_servico_po(self, id_solicitacao: str, quem: str):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            from constants import STATUS_CONCLUIDO_PO

            existing = self._execute(
                self._table("demandas").select("registro")
                .eq("id", id_solicitacao).limit(1)
            )
            if not existing:
                return False, "Solicitacao nao encontrada."

            registro_atual = existing[0].get("registro", "") if isinstance(existing[0], dict) else ""
            linha = f"[APROVADO {quem}]: Servico concluido pelo PO"
            novo_registro = f"{registro_atual}\n{linha}".strip() if registro_atual else linha

            self._execute(
                self._table("demandas").update({
                    "status": STATUS_CONCLUIDO_PO,
                    "registro": novo_registro,
                }).eq("id", id_solicitacao)
            )
            return True, "Servico marcado como concluido pelo PO."
        except Exception as e:
            return False, str(e)

    def concluir_servico_infraestrutura(self, id_solicitacao: str, quem: str):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            from constants import STATUS_CONCLUIDO_INFRA

            existing = self._execute(
                self._table("demandas").select("registro")
                .eq("id", id_solicitacao).limit(1)
            )
            if not existing:
                return False, "Solicitacao nao encontrada."

            registro_atual = existing[0].get("registro", "") if isinstance(existing[0], dict) else ""
            linha = f"[APROVADO {quem}]: Servico concluido pela Infraestrutura"
            novo_registro = f"{registro_atual}\n{linha}".strip() if registro_atual else linha

            self._execute(
                self._table("demandas").update({
                    "status": STATUS_CONCLUIDO_INFRA,
                    "registro": novo_registro,
                }).eq("id", id_solicitacao)
            )
            return True, "Servico marcado como concluido pela Infraestrutura."
        except Exception as e:
            return False, str(e)

    def get_aproved_data(self, table_name: str):
        if not self.is_connected:
            return [HEADER_DEMANDA]
        try:
            from constants import status_alvos_bloco_aprovacao
            status_list = status_alvos_bloco_aprovacao(table_name)

            data = self._execute(
                self._table("demandas").select("*")
                .in_("status", status_list)
                .order("created_at", desc=True)
            )
            rows = [_demanda_row_to_list(_demanda_db_to_app(row)) for row in data]
            return [HEADER_DEMANDA] + rows
        except Exception as e:
            print(f"[SupabaseManager] Erro get_aproved_data: {e}")
            return [HEADER_DEMANDA]

    def update_aproved_priority(self, table_name: str, id_solicitacao: str, direction: int):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            existing = self._execute(
                self._table("demandas").select("prioridade")
                .eq("id", id_solicitacao).limit(1)
            )
            if not existing:
                return False, "Solicitacao nao encontrada."

            pri = int(existing[0].get("prioridade", "0"))
            nova_pri = str(max(0, pri - direction))

            self._execute(
                self._table("demandas").update({"prioridade": nova_pri})
                .eq("id", id_solicitacao)
            )
            return True, "Prioridade atualizada."
        except Exception as e:
            return False, str(e)

    def delete_item_from_aproved(self, table_name: str, t_id: str):
        return self.delete_solicitacao(t_id)

    def clear_aproved_table_all(self, table_name: str, om_to_filter: str = None):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            from constants import status_alvos_bloco_aprovacao
            status_list = status_alvos_bloco_aprovacao(table_name)

            for s in status_list:
                query = self._table("demandas").delete().eq("status", s)
                if om_to_filter:
                    query = query.eq("om", om_to_filter)
                self._execute(query)
            return True, "Tabela limpa com sucesso."
        except Exception as e:
            return False, str(e)

    def get_detalhamento(self, id_solicitacao: str):
        if not self.is_connected:
            return []
        try:
            data = self._execute(
                self._table("demandas").select("detalhamento")
                .eq("id", id_solicitacao).limit(1)
            )
            if data and data[0].get("detalhamento"):
                return data[0]["detalhamento"]
            return []
        except Exception as e:
            print(f"[SupabaseManager] Erro get_detalhamento: {e}")
            return []

    def salvar_detalhamento(self, id_solicitacao: str, itens: list):
        if not self.is_connected:
            return False, "Supabase nao conectado."
        try:
            self._execute(
                self._table("demandas").update({"detalhamento": itens})
                .eq("id", id_solicitacao)
            )
            return True, "Detalhamento salvo com sucesso!"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _convert_legacy_list(data):
        if not data or not isinstance(data[0], list):
            return data
        headers = data[0]
        result = []
        for row in data[1:]:
            d = {}
            for idx, val in enumerate(row):
                key = headers[idx] if idx < len(headers) else f"col{idx}"
                d[key] = val
            result.append(d)
        return result

    def import_from_json(self, usuarios_path: str, demandas_path: str):
        resultados = {"usuarios": 0, "demandas": 0, "erros": []}

        if not self.is_connected:
            resultados["erros"].append("Supabase nao conectado.")
            return resultados

        try:
            if os.path.exists(usuarios_path):
                with open(usuarios_path, "r", encoding="utf-8") as f:
                    users_raw = json.load(f)
                users = self._convert_legacy_list(users_raw)
                for u in users:
                    if isinstance(u, dict):
                        try:
                            self._execute(
                                self._table("usuarios").upsert({
                                    "om": u.get("OM", ""),
                                    "nome": u.get("Nome", ""),
                                    "identidade": str(u.get("Identidade", "")).strip().lstrip("0"),
                                    "funcao": u.get("Funcao", ""),
                                    "senha": u.get("Senha", ""),
                                    "status": u.get("Status", "Ativo"),
                                    "hidden_ids": u.get("HiddenIDs", ""),
                                }, on_conflict="identidade")
                            )
                            resultados["usuarios"] += 1
                        except Exception as e:
                            resultados["erros"].append(f"Usuario: {e}")
        except Exception as e:
            resultados["erros"].append(f"Erro ao ler {usuarios_path}: {e}")

        try:
            if os.path.exists(demandas_path):
                with open(demandas_path, "r", encoding="utf-8") as f:
                    demandas_raw = json.load(f)
                demandas = self._convert_legacy_list(demandas_raw)
                for d in demandas:
                    if isinstance(d, dict):
                        try:
                            detalhamento = d.get("Detalhamento")
                            row = {
                                "id": str(d.get("ID", "")),
                                "data": d.get("Data", ""),
                                "status": d.get("Status", ""),
                                "solicitante": d.get("Solicitante", ""),
                                "local": d.get("Local", ""),
                                "tipo": d.get("Tipo", ""),
                                "descricao": d.get("Descricao", d.get("Descricao", "")),
                                "urgencia": d.get("Urgencia", d.get("Urgencia", "")),
                                "om": d.get("OM", ""),
                                "prioridade": d.get("Prioridade", "0"),
                                "fotourl": d.get("FotoURL", ""),
                                "parecerpo": d.get("ParecerPO", ""),
                                "registro": d.get("Registro", ""),
                                "detalhamento": detalhamento if detalhamento else None,
                            }
                            self._execute(
                                self._table("demandas").upsert(row, on_conflict="id")
                            )
                            resultados["demandas"] += 1
                        except Exception as e:
                            resultados["erros"].append(f"Demanda: {e}")
        except Exception as e:
            resultados["erros"].append(f"Erro ao ler {demandas_path}: {e}")

        return resultados
