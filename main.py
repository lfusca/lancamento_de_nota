###############################################################################
#  Lançamento de notas/feedback – FIAP Moodle + Streamlit                     #
#  Versão: 02-jul-2025 – **SQLite → Oracle**                                  #
#  • Driver: python-oracledb (pool)                                           #
#  • Conversão automática de CLOB → str (feedback)                            #
###############################################################################
import streamlit as st
import pandas as pd, time
import oracledb
import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException,
    ElementNotInteractableException)
from urllib.parse import urlparse
from bs4 import BeautifulSoup

load_dotenv()
# --------------------------------------------------------------------------- #
# CREDENCIAIS ORACLE (ajuste conforme necessário)                             #
# --------------------------------------------------------------------------- #
ORCL_USER = os.getenv("ORCL_USER")
ORCL_PWD  = os.getenv("ORCL_PWD")
ORCL_DSN  = os.getenv("ORCL_DSN")

POOL = oracledb.create_pool(
    user=ORCL_USER,
    password=ORCL_PWD,
    dsn=ORCL_DSN,
    min=1, max=5, increment=1
)

# --------------------------------------------------------------------------- #
# CONFIGURAÇÕES DIVERSAS                                                      #
# --------------------------------------------------------------------------- #
LOGIN_URL = os.getenv("LOGIN_URL")
USERNAME  = os.getenv("MOODLE_USER")
PASSWORD  = os.getenv("PASSWORD")
HEADLESS  = True                           # True = headless Chrome

# --------------------------------------------------------------------------- #
# CAMADA DE BANCO (substitui SQLite)                                          #
# --------------------------------------------------------------------------- #
def _to_bind(sql: str) -> str:
    """Converte '?' para ':1, :2…' para usar os mesmos placeholders do SQLite."""
    if "?" not in sql:
        return sql
    parts = sql.split("?")
    out = parts[0]
    for i in range(1, len(parts)):
        out += f":{i}" + parts[i]
    return out


def _row_fix_lob(row):
    """Converte objetos oracledb.LOB → str (evita mostrar <oracledb.LOB …>)"""
    return tuple(col.read() if isinstance(col, oracledb.LOB) else col
                 for col in row)


def executar(sql: str, params=(), fetch=False):
    """Executa SQL no Oracle mantendo a API original (SQLite)."""
    sql = _to_bind(sql)
    with POOL.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        if fetch:
            rows = cur.fetchall()
            rows = [_row_fix_lob(r) for r in rows]
            return rows
        conn.commit()


def inicializar_banco():
    """As tabelas já existem no Oracle; função mantida para compatibilidade."""
    pass

# --------------------------------------------------------------------------- #
# UTILITÁRIOS                                                                 #
# --------------------------------------------------------------------------- #
def iniciar_navegador(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=opts)


def somente_texto(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n").strip()


def fmt_peso(v):
    if v is None:
        return ""
    v = round(v, 4)
    return str(int(v)) if v.is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")

# --------------------------------------------------------------------------- #
# MOODLE – CAPTURA E AÇÕES                                                    #
# --------------------------------------------------------------------------- #
def logar_moodle(drv):
    drv.get(LOGIN_URL)
    WebDriverWait(drv, 10).until(EC.presence_of_element_located((By.ID, "username")))
    drv.find_element(By.ID, "username").send_keys(USERNAME)
    drv.find_element(By.ID, "password").send_keys(PASSWORD + Keys.RETURN)
    WebDriverWait(drv, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))


def capturar_nome_atividade(drv, url):
    drv.get(url); time.sleep(2)
    try:
        return drv.find_element(By.CSS_SELECTOR, "div.page-header-headings h1").text.strip()
    except:
        return drv.title.replace(" - Moodle FIAP", "").strip()


def obter_nota_feedback(drv, id_atividade, id_aluno):
    drv.get(f"https://on.fiap.com.br/mod/assign/view.php?"
            f"id={id_atividade}&rownum=0&action=grader&userid={id_aluno}")
    try:
        WebDriverWait(drv, 8).until(
            EC.presence_of_element_located((By.ID, "id_grade")))
        nota = drv.find_element(By.ID, "id_grade").get_attribute("value").strip()
    except TimeoutException:
        nota = ""
    fb_raw = ""
    try:
        WebDriverWait(drv, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR,
            "#id_assignfeedbackcomments_editor_ifr,#id_assignfeedbackcomments_editor")))
        if drv.find_elements(By.ID, "id_assignfeedbackcomments_editor_ifr"):
            iframe = drv.find_element(By.ID, "id_assignfeedbackcomments_editor_ifr")
            drv.switch_to.frame(iframe)
            fb_raw = drv.find_element(By.CSS_SELECTOR, "body#tinymce").get_attribute("innerHTML")
            drv.switch_to.default_content()
        else:
            el = drv.find_element(By.ID, "id_assignfeedbackcomments_editor")
            fb_raw = el.get_attribute("value") if el.tag_name.lower() == "textarea" else el.get_attribute("innerHTML")
    except:
        pass
    return nota, somente_texto(fb_raw)


def listar_alunos(drv, id_atividade, completo=False):
    drv.get(f"https://on.fiap.com.br/mod/assign/view.php?id={id_atividade}&action=grading")
    time.sleep(3)
    try:
        drv.find_element(By.LINK_TEXT, "Todos").click(); time.sleep(2)
    except:
        pass
    soup = BeautifulSoup(drv.page_source, "html.parser")
    alunos = []
    for tr in soup.select("table tbody tr"):
        chk = tr.select_one('input[name="selectedusers"]')
        if not chk:
            continue
        id_aluno = chk["value"].strip()
        nota, fb = ("", "")
        if completo:
            nota, fb = obter_nota_feedback(drv, id_atividade, id_aluno)
        alunos.append({
            "id_aluno": id_aluno,
            "rm": tr.select_one("td.c4.username").text.strip(),
            "nome": tr.select_one("td.c2").text.strip(),
            "grupo": tr.select_one("td.c6").text.strip() if tr.select_one("td.c6") else "",
            "nota": nota,
            "feedback": fb,
            "ir_alem": ""
        })
    return alunos


def escrever_feedback(drv, texto):
    if drv.find_elements(By.ID, "id_assignfeedbackcomments_editor_ifr"):
        ifr = drv.find_element(By.ID, "id_assignfeedbackcomments_editor_ifr")
        drv.switch_to.frame(ifr)
        drv.execute_script("document.body.innerHTML = arguments[0];", texto.replace("\n", "<br>"))
        drv.switch_to.default_content()
    else:
        el = drv.find_element(By.ID, "id_assignfeedbackcomments_editor")
        tag = el.tag_name.lower()
        try:
            if tag == "textarea":
                el.clear(); el.send_keys(texto)
            else:
                el.send_keys(Keys.CONTROL + "a"); el.send_keys(texto)
        except ElementNotInteractableException:
            script = ("arguments[0].value = arguments[1];"
                      if tag == "textarea"
                      else "arguments[0].innerText = arguments[1];")
            drv.execute_script(script, el, texto)


def salvar_grade(drv):
    drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(0.4)
    btn = None
    for by, val in [
        (By.NAME, "savechanges"),
        (By.CSS_SELECTOR, "button.btn-grader"),
        (By.XPATH, "//button[contains(normalize-space(text()),'Salvar mudanças')]")
    ]:
        try:
            btn = drv.find_element(by, val); break
        except:
            pass
    if not btn:
        raise RuntimeError("Botão 'Salvar mudanças' não encontrado.")
    drv.execute_script("arguments[0].scrollIntoView(true);", btn)
    btn.click()
    end = time.time() + 15
    while time.time() < end:
        try:
            if drv.find_elements(By.CSS_SELECTOR, ".alert-success"): return
            if not btn.is_enabled() or btn.get_attribute("disabled"): return
        except StaleElementReferenceException:
            return
        time.sleep(0.5)
    print("Aviso: Moodle não respondeu em 15 s.")

# --------------------------------------------------------------------------- #
# STREAMLIT INTERFACE                                                         #
# --------------------------------------------------------------------------- #
def main():
    st.title("Gerenciamento de Atividades e Alunos – FIAP")

    menu = st.sidebar.selectbox(
        "Menu",
        ["Inserir Nova Atividade",
         "Visualizar / Gerenciar Atividades",
         "Editar Notas e Feedbacks"]
    )

    # ========================= 1 INSERIR NOVA ATIVIDADE ==================== #
    if menu == "Inserir Nova Atividade":
        url   = st.text_input("URL da atividade:")
        fase  = st.text_input("Fase (ex: Capítulo 1):")
        turma = st.text_input("Turma (ex: 2A, 3B):")
        nota_max = st.number_input(
            "Nota máxima (peso):", min_value=0.0, step=0.01, format="%.4f")

        col1, col2 = st.columns(2)
        modo = None
        if col1.button("Capturar rápido (só alunos)"):                    modo = "basico"
        if col2.button("Capturar completo (alunos + notas + feedback)"):  modo = "completo"

        if modo and url and fase and turma:
            id_atv = urlparse(url).query.split("id=")[1].split("&")[0]
            drv = iniciar_navegador(HEADLESS)
            try:
                logar_moodle(drv)
                nome = capturar_nome_atividade(drv, url)
                alunos = listar_alunos(drv, id_atv, completo=(modo == "completo"))

                executar("""INSERT INTO atividades
                            (turma, fase, id_atividade, nome_atividade,
                             url, nota_maxima)
                            VALUES (?,?,?,?,?,?)""",
                         (turma.strip(), fase.strip(), id_atv, nome, url,
                          float(round(nota_max, 4))))
                for a in alunos:
                    executar("""INSERT INTO alunos
                        (id_atividade, id_aluno, rm, nome, grupo,
                         nota, feedback, ir_alem)
                        VALUES (?,?,?,?,?,?,?,?)""",
                             (id_atv, a["id_aluno"], a["rm"], a["nome"],
                              a["grupo"], a["nota"], a["feedback"], ""))
                st.success(f"{len(alunos)} alunos cadastrados "
                           f"({'completos' if modo == 'completo' else 'básicos'}).")
            finally:
                drv.quit()

    # ===================== 2 VISUALIZAR / GERENCIAR ATIVIDADES ============= #
    elif menu == "Visualizar / Gerenciar Atividades":
        turmas = executar("SELECT DISTINCT turma FROM atividades", fetch=True)
        if not turmas:
            st.info("Nenhuma atividade."); return
        turma_sel = st.selectbox("Turma", [t[0] for t in turmas])

        fases = executar("SELECT DISTINCT fase FROM atividades WHERE turma=?",
                         (turma_sel,), fetch=True)
        if not fases:
            st.info("Sem fases."); return
        fase_sel = st.selectbox("Fase", [f[0] for f in fases])

        atvs = executar("""SELECT id, id_atividade, nome_atividade,
                                  turma, fase, nota_maxima
                           FROM atividades
                           WHERE turma=? AND fase=?""",
                        (turma_sel, fase_sel), True)
        if not atvs:
            st.info("Sem atividades."); return

        df = pd.DataFrame(atvs,
                          columns=["id_reg", "id_atividade", "nome_atividade",
                                   "turma", "fase", "nota_maxima"])
        df["Sel"] = False

        st.subheader("Atividades")
        edit = st.data_editor(
            df[["Sel", "id_atividade", "nome_atividade",
                "turma", "fase", "nota_maxima"]],
            column_config={
                "nota_maxima": st.column_config.NumberColumn(
                    label="Nota Máxima", format="%.4f", step=0.01)
            },
            num_rows="fixed", use_container_width=True
        )

        col_sav, col_del = st.columns(2)
        if col_sav.button("Salvar alterações (somente selecionados)"):
            ok = False
            for _, r in edit.iterrows():
                if not r["Sel"]: continue
                ok = True
                id_reg = int(df.loc[df["id_atividade"] == r["id_atividade"], "id_reg"].values[0])
                executar("""UPDATE atividades
                             SET turma=?, fase=?, nota_maxima=?
                             WHERE id=?""",
                         (str(r["turma"]).strip(),
                          str(r["fase"]).strip(),
                          float(round(float(r["nota_maxima"]), 4)) if r["nota_maxima"] != "" else None,
                          id_reg))
            st.success("Metadados atualizados." if ok else "Nenhuma linha selecionada.")
            if ok: st.rerun()

        if col_del.button("Apagar selecionados"):
            ok = False
            for _, r in edit.iterrows():
                if not r["Sel"]: continue
                ok = True
                id_reg = int(df.loc[df["id_atividade"] == r["id_atividade"], "id_reg"].values[0])
                id_atv = str(r["id_atividade"])
                executar("DELETE FROM alunos WHERE id_atividade=?", (id_atv,))
                executar("DELETE FROM atividades WHERE id=?", (id_reg,))
            st.success("Atividades apagadas." if ok else "Nenhuma linha selecionada.")
            if ok: st.rerun()

    # ===================== 3 EDITAR NOTAS & FEEDBACKS ====================== #
    else:
        turmas = executar("SELECT DISTINCT turma FROM atividades", fetch=True)
        if not turmas:
            st.info("Nenhuma atividade."); return
        turma_sel = st.selectbox("Turma", [t[0] for t in turmas])

        fases = executar("SELECT DISTINCT fase FROM atividades WHERE turma=?",
                         (turma_sel,), fetch=True)
        if not fases:
            st.info("Sem fases."); return
        fase_sel = st.selectbox("Fase", [f[0] for f in fases])

        atvs = executar("""SELECT id_atividade, nome_atividade, nota_maxima
                           FROM atividades WHERE turma=? AND fase=?""",
                        (turma_sel, fase_sel), True)
        if not atvs:
            st.info("Sem atividades."); return
        atv_opts = [f"{a[0]} — {a[1]} (peso: {fmt_peso(a[2])})" for a in atvs]
        atv_sel = st.selectbox("Atividade", atv_opts)
        id_atv  = atv_sel.split(" — ")[0]
        nota_max_atv = next(a[2] for a in atvs if str(a[0]) == id_atv)
        st.markdown(f"**Nota máxima (peso): {fmt_peso(nota_max_atv)}**")

        alunos = executar("""SELECT id, id_aluno, rm, nome, grupo,
                                    nota, feedback, ir_alem
                             FROM alunos WHERE id_atividade=?""",
                          (id_atv,), True)
        df = pd.DataFrame(alunos,
                          columns=["id_reg", "id_aluno", "rm", "nome",
                                   "grupo", "nota", "feedback", "ir_alem"])
        df["Sel"] = False
        df["ir_alem"] = df["ir_alem"].fillna("").astype(str)

        if st.checkbox("Selecionar todos"):
            df.loc[:, "Sel"] = True

        edit = st.data_editor(
            df[["Sel", "id_aluno", "rm", "nome", "grupo",
                "nota", "feedback", "ir_alem"]],
            column_config={
                "ir_alem": st.column_config.SelectboxColumn(
                    label="Ir Além", options=["", "Sim", "Não"], width="small")
            },
            num_rows="fixed", use_container_width=True
        )

        if st.button("Importar do Moodle (somente selecionados)"):
            drv = iniciar_navegador(HEADLESS)
            try:
                logar_moodle(drv)
                for _, r in edit.iterrows():
                    if not r["Sel"]: continue
                    id_aluno = str(r["id_aluno"])
                    id_reg   = int(df.loc[df["id_aluno"] == id_aluno, "id_reg"].values[0])
                    nota, fb = obter_nota_feedback(drv, id_atv, id_aluno)
                    executar("UPDATE alunos SET nota=?, feedback=? WHERE id=?",
                             (nota, fb, id_reg))
                    st.success(f"{r['nome']} importado.")
            finally:
                drv.quit()
            st.rerun()

        if st.button("Salvar Alterações (somente selecionados)"):
            drv = iniciar_navegador(HEADLESS)
            try:
                logar_moodle(drv)
                for _, r in edit.iterrows():
                    if not r["Sel"]: continue
                    id_aluno = str(r["id_aluno"])
                    id_reg   = int(df.loc[df["id_aluno"] == id_aluno, "id_reg"].values[0])
                    nota_env = str(r["nota"]).strip()
                    fb_env   = somente_texto(r["feedback"])
                    ir_env   = r["ir_alem"] or ""

                    drv.get(f"https://on.fiap.com.br/mod/assign/view.php?"
                            f"id={id_atv}&rownum=0&action=grader&userid={id_aluno}")
                    WebDriverWait(drv, 8).until(
                        EC.presence_of_element_located((By.ID, "id_grade")))
                    campo = drv.find_element(By.ID, "id_grade")
                    try:
                        campo.clear(); campo.send_keys(nota_env)
                    except ElementNotInteractableException:
                        drv.execute_script("arguments[0].value=arguments[1];",
                                           campo, nota_env)
                    escrever_feedback(drv, fb_env)
                    salvar_grade(drv)

                    executar("""UPDATE alunos
                                 SET nota=?, feedback=?, ir_alem=?
                                 WHERE id=?""",
                             (nota_env, fb_env, ir_env, id_reg))
                    st.success(f"{r['nome']} sincronizado.")
            finally:
                drv.quit()
            st.rerun()

        if st.button("Salvar Localmente (somente selecionados)"):
            for _, r in edit.iterrows():
                if not r["Sel"]: continue
                id_aluno = str(r["id_aluno"])
                id_reg   = int(df.loc[df["id_aluno"] == id_aluno, "id_reg"].values[0])
                executar("""UPDATE alunos
                             SET nota=?, feedback=?, ir_alem=?
                             WHERE id=?""",
                         (r["nota"], r["feedback"], r["ir_alem"] or "", id_reg))
            st.success("Alterações locais gravadas.")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    inicializar_banco()
    main()
