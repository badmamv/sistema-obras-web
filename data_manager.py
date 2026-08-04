import os
import sys
import json
import time

from PyQt6.QtCore import pyqtSignal, QObject
from constants import *


class FirebaseListener(QObject):
    update_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        from PyQt6.QtCore import QFileSystemWatcher
        self.watcher = QFileSystemWatcher()
        self.watcher.fileChanged.connect(self.on_file_changed)
        self._is_writing = False

    def on_file_changed(self, path):
        if self._is_writing:
            return
        self.update_signal.emit()

    def add_watch_path(self, path):
        if path and os.path.exists(path):
            if path not in self.watcher.files():
                self.watcher.addPath(path)

    def remove_watch_path(self, path):
        if path and path in self.watcher.files():
            self.watcher.removePath(path)

    def unsubscribe(self):
        files = self.watcher.files()
        if files:
            self.watcher.removePaths(files)


class LocalDataManager:
    def __init__(self):
        self.base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.usuarios_path = os.path.join(self.base_path, USUARIOS_FILE)
        self.demandas_path = os.path.join(self.base_path, ENTRADA_FILE)
        self._ensure_file_exists(self.usuarios_path, [["OM", "Nome", "Identidade", "Funcao", "Senha", "Status", "HiddenIDs"]])
        self._ensure_file_exists(self.demandas_path, [])
        self.listener = FirebaseListener()

    def _ensure_file_exists(self, path, default_content):
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(default_content, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"Erro ao inicializar arquivo {path}: {e}")

    def listen_demandas(self, callback):
        try:
            self.listener.update_signal.connect(callback)
            self.listener.add_watch_path(self.demandas_path)
            self.listener.add_watch_path(self.usuarios_path)
        except Exception as e:
            print(f"Erro ao configurar listener: {e}")

    def _read_json(self, filepath):
        for _ in range(5):
            try:
                if not os.path.exists(filepath):
                    return []
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        return []
                    data = json.loads(content)
                    if data and isinstance(data[0], list):
                        headers = data[0]
                        dict_list = []
                        for row in data[1:]:
                            d = {}
                            for idx, val in enumerate(row):
                                if idx < len(headers):
                                    d[headers[idx]] = val
                            dict_list.append(d)
                        data = dict_list
                    return data
            except (IOError, json.JSONDecodeError, PermissionError):
                time.sleep(0.1)
        return []

    def _write_json(self, filepath, data):
        if hasattr(self, 'listener'):
            self.listener._is_writing = True
        success = False
        for _ in range(5):
            try:
                temp_filepath = filepath + ".tmp"
                with open(temp_filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                if os.path.exists(filepath):
                    os.remove(filepath)
                os.rename(temp_filepath, filepath)
                success = True
                break
            except (IOError, PermissionError):
                time.sleep(0.1)
        if hasattr(self, 'listener'):
            self.listener._is_writing = False
        return success

    def get_users(self):
        return self._read_json(self.usuarios_path)

    def add_user(self, om, nome, identidade, funcao, senha):
        try:
            identidade = str(identidade).strip().lstrip('0')
            users = self.get_users()
            for u in users:
                u_funcao = u.get("Funcao", "")
                u_om = u.get("OM", "")
                if funcao == "Fisc Adm Base" and u_funcao == funcao:
                    return False, f"Ja existe um Fisc Adm Base cadastrado no sistema ({u.get('Nome')} na {u_om})."
                elif funcao == "Chefe da Secao de Infraestrutura" and u_funcao == funcao:
                    return False, f"Ja existe um Chefe da Secao de Infraestrutura cadastrado no sistema ({u.get('Nome')} na {u_om})."
                elif funcao == "Secao de Servicos Gerais" and u_funcao == funcao:
                    return False, f"Ja existe um usuario da Secao de Servicos Gerais cadastrado no sistema ({u.get('Nome')} na {u_om})."
                elif funcao != "Outros" and u_funcao == funcao and u_om == om:
                    return False, f"Ja existe um {funcao} cadastrado para a {om}."
                if str(u.get("Identidade")).strip().lstrip('0') == identidade:
                    return False, "Esta identidade ja esta cadastrada."
            user_data = {
                "OM": om, "Nome": nome, "Identidade": identidade,
                "Funcao": funcao, "Senha": gerar_hash_senha(senha),
                "Status": "Ativo", "HiddenIDs": ""
            }
            users.append(user_data)
            self._write_json(self.usuarios_path, users)
            return True, "Usuario cadastrado com sucesso."
        except Exception as e:
            return False, f"Erro ao cadastrar: {e}"

    def delete_user(self, identidade):
        try:
            identidade = str(identidade).strip().lstrip('0')
            users = self.get_users()
            novos_users = [u for u in users if str(u.get("Identidade")).strip().lstrip('0') != identidade]
            self._write_json(self.usuarios_path, novos_users)
            return True, "Usuario excluido com sucesso."
        except Exception as e:
            return False, str(e)

    def add_solicitacao(self, data_list):
        try:
            doc_id = str(data_list[0])
            demandas = self._read_json(self.demandas_path)
            doc_data = {
                "ID": doc_id, "Data": data_list[1], "Status": data_list[2],
                "Solicitante": data_list[3], "Local": data_list[4], "Tipo": data_list[5],
                "Descrição": data_list[6], "Urgência": data_list[7], "OM": data_list[8],
                "Prioridade": "0", "FotoURL": data_list[9] if len(data_list) > 9 else "",
                "ParecerPO": "", "Registro": "",
            }
            demandas = [d for d in demandas if str(d.get("ID")) != doc_id]
            demandas.append(doc_data)
            self._write_json(self.demandas_path, demandas)
            return True, "Solicitacao enviada com sucesso!"
        except Exception as e:
            return False, str(e)

    def get_data_from_sheet(self, sheet_name):
        try:
            if "Usuarios" in sheet_name:
                users = self.get_users()
                header = ["OM", "Nome", "Identidade", "Funcao", "Senha", "Status", "HiddenIDs"]
                rows = [[u.get(h, "") for h in header] for u in users]
                return [header] + rows
            demandas = self._read_json(self.demandas_path)
            rows = [linha_demanda_de_doc(d) for d in demandas]
            return [HEADER_DEMANDA] + rows
        except Exception:
            return []

    def update_status(self, id_solicitacao, novo_status, motivo=None, quem=None, prefix=None):
        try:
            demandas = self._read_json(self.demandas_path)
            encontrado = False
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    d["Status"] = novo_status
                    if motivo:
                        registro = d.get("Registro", "")
                        if prefix:
                            prefixo = prefix
                        elif str(motivo).startswith("Aprovado"):
                            prefixo = "APROVADO"
                        else:
                            prefixo = "RETORNO"
                        linha = f"[{prefixo} {quem}]: {motivo}" if quem else f"[{prefixo}]: {motivo}"
                        d["Registro"] = f"{registro}\n{linha}".strip() if registro else linha
                    encontrado = True
                    break
            if not encontrado:
                return False, "Solicitacao nao encontrada."
            self._write_json(self.demandas_path, demandas)
            return True, "Status atualizado com sucesso."
        except Exception as e:
            return False, str(e)

    def update_solicitacao(self, id_solicitacao, dados):
        try:
            demandas = self._read_json(self.demandas_path)
            encontrado = False
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    d["Data"] = dados[0]; d["Status"] = dados[1]
                    d["Solicitante"] = dados[2]; d["Local"] = dados[3]
                    d["Tipo"] = dados[4]; d["Descrição"] = dados[5]
                    d["Urgência"] = dados[6]; d["OM"] = dados[7]
                    d["FotoURL"] = dados[8] if len(dados) > 8 else ""
                    encontrado = True
                    break
            if not encontrado:
                return False, "Solicitacao nao encontrada."
            self._write_json(self.demandas_path, demandas)
            return True, "Solicitacao atualizada com sucesso!"
        except Exception as e:
            return False, str(e)

    def delete_solicitacao(self, id_solicitacao):
        try:
            demandas = self._read_json(self.demandas_path)
            novas_demandas = [d for d in demandas if str(d.get("ID")) != str(id_solicitacao)]
            self._write_json(self.demandas_path, novas_demandas)
            return True, "Solicitacao excluida com sucesso."
        except Exception as e:
            return False, str(e)

    def hide_solicitacao_for_user(self, identidade_usuario, ids_solicitacao):
        try:
            identidade_usuario = str(identidade_usuario).strip().lstrip('0')
            users = self.get_users()
            encontrado = False
            for u in users:
                if str(u.get("Identidade")).strip().lstrip('0') == identidade_usuario:
                    current_hidden = u.get("HiddenIDs", "")
                    hidden_list = [sid.strip() for sid in str(current_hidden).split(",") if sid.strip()]
                    if isinstance(ids_solicitacao, list):
                        for sid in ids_solicitacao:
                            if str(sid) not in hidden_list:
                                hidden_list.append(str(sid))
                    else:
                        if str(ids_solicitacao) not in hidden_list:
                            hidden_list.append(str(ids_solicitacao))
                    u["HiddenIDs"] = ",".join(hidden_list)
                    encontrado = True
                    break
            if not encontrado:
                return False, "Usuario nao encontrado."
            self._write_json(self.usuarios_path, users)
            return True, "Item ocultado com sucesso."
        except Exception as e:
            return False, str(e)

    def move_to_aproved_table(self, id_solicitacao, table_name):
        return self.update_status(id_solicitacao, status_para_bloco_aprovacao(table_name))

    def parecer_servicos_gerais_para_fisc_adm(self, id_solicitacao, parecer_tag, quem):
        try:
            demandas = self._read_json(self.demandas_path)
            encontrado = False
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    status_atual = d.get("Status", "")
                    if status_atual != STATUS_ANALISE_SERVICOS_GERAIS:
                        status_sg = status_alvos_bloco_aprovacao("Aprovados_Servicos_Gerais")
                        if status_atual not in status_sg:
                            return False, "Esta demanda nao esta aguardando analise da Secao de Servicos Gerais."
                    if parecer_tag == TAG_PO_EXECUTA:
                        novo_status = STATUS_EM_EXECUCAO_PO
                    else:
                        novo_status = TAG_PO_NAO_EXECUTA
                    registro = d.get("Registro", "")
                    linha = f"[APROVADO {quem}]: Parecer {parecer_tag}"
                    novo_registro = f"{registro}\n{linha}".strip() if registro else linha
                    d["Status"] = novo_status
                    d["ParecerPO"] = parecer_tag
                    d["Registro"] = novo_registro
                    encontrado = True
                    break
            if not encontrado:
                return False, "Solicitacao nao encontrada."
            self._write_json(self.demandas_path, demandas)
            if parecer_tag == TAG_PO_EXECUTA:
                return True, "Parecer registrado. A demanda esta no seu Painel de Aprovacoes para acompanhamento da execucao."
            else:
                return True, "Parecer registrado. A demanda foi devolvida ao Fisc Adm para encaminhamento."
        except Exception as e:
            return False, str(e)

    def concluir_servico_po(self, id_solicitacao, quem):
        try:
            demandas = self._read_json(self.demandas_path)
            encontrado = False
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    registro = d.get("Registro", "")
                    linha = f"[APROVADO {quem}]: Servico concluido pelo PO"
                    novo_registro = f"{registro}\n{linha}".strip() if registro else linha
                    d["Status"] = STATUS_CONCLUIDO_PO
                    d["Registro"] = novo_registro
                    encontrado = True
                    break
            if not encontrado:
                return False, "Solicitacao nao encontrada."
            self._write_json(self.demandas_path, demandas)
            return True, "Servico marcado como concluido pelo PO."
        except Exception as e:
            return False, str(e)

    def concluir_servico_infraestrutura(self, id_solicitacao, quem):
        try:
            demandas = self._read_json(self.demandas_path)
            encontrado = False
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    registro = d.get("Registro", "")
                    linha = f"[APROVADO {quem}]: Servico concluido pela Infraestrutura"
                    novo_registro = f"{registro}\n{linha}".strip() if registro else linha
                    d["Status"] = STATUS_CONCLUIDO_INFRA
                    d["Registro"] = novo_registro
                    encontrado = True
                    break
            if not encontrado:
                return False, "Solicitacao nao encontrada."
            self._write_json(self.demandas_path, demandas)
            return True, "Servico marcado como concluido pela Infraestrutura."
        except Exception as e:
            return False, str(e)

    def get_aproved_data(self, table_name):
        try:
            demandas = self._read_json(self.demandas_path)
            rows = []
            vistos = set()
            for status_alvo in status_alvos_bloco_aprovacao(table_name):
                for d in demandas:
                    if d.get("Status") == status_alvo:
                        doc_id = d.get("ID")
                        if doc_id in vistos:
                            continue
                        vistos.add(doc_id)
                        rows.append(linha_demanda_de_doc(d))
            return [HEADER_DEMANDA] + rows
        except Exception:
            return [HEADER_DEMANDA]

    def update_aproved_priority(self, table_name, id_solicitacao, direction):
        try:
            demandas = self._read_json(self.demandas_path)
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    pri = int(d.get("Prioridade", "0"))
                    d["Prioridade"] = str(max(0, pri - direction))
                    break
            self._write_json(self.demandas_path, demandas)
            return True, "Prioridade atualizada localmente."
        except Exception as e:
            return False, str(e)

    def delete_item_from_aproved(self, table_name, t_id):
        return self.delete_solicitacao(t_id)

    def clear_aproved_table_all(self, table_name, om_to_filter=None):
        try:
            demandas = self._read_json(self.demandas_path)
            status_alvos = status_alvos_bloco_aprovacao(table_name)
            novas_demandas = []
            for d in demandas:
                if d.get("Status") in status_alvos:
                    if om_to_filter and d.get("OM") != om_to_filter:
                        novas_demandas.append(d)
                else:
                    novas_demandas.append(d)
            self._write_json(self.demandas_path, novas_demandas)
            return True, "Tabela limpa com sucesso."
        except Exception as e:
            return False, str(e)

    def connect(self):
        return True, "Conexao Local Ativa."

    def open_spreadsheet(self, sheet_id=None):
        return True, "Banco de Dados Local Carregado."

    def get_detalhamento(self, id_solicitacao):
        try:
            demandas = self._read_json(self.demandas_path)
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    return d.get("Detalhamento", [])
            return []
        except Exception as e:
            print(f"Erro ao obter detalhamento: {e}")
            return []

    def salvar_detalhamento(self, id_solicitacao, itens):
        try:
            demandas = self._read_json(self.demandas_path)
            encontrado = False
            for d in demandas:
                if str(d.get("ID")) == str(id_solicitacao):
                    d["Detalhamento"] = itens
                    encontrado = True
                    break
            if not encontrado:
                return False, "Solicitacao nao encontrada."
            self._write_json(self.demandas_path, demandas)
            return True, "Detalhamento salvo com sucesso!"
        except Exception as e:
            return False, str(e)
