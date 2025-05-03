###############################################################################
#  Lançamento de notas/feedback – FIAP Moodle + Streamlit                     #
#  Versão: 09‑mai‑2025 (HEADLESS por constante)                               #
###############################################################################
import streamlit as st
import sqlite3, pandas as pd, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, ElementNotInteractableException
)
from urllib.parse import urlparse
from bs4 import BeautifulSoup


# --------------------------------------------------------------------------- #
# CONFIGURAÇÕES GERAIS                                                        #
# --------------------------------------------------------------------------- #
LOGIN_URL = "https://on.fiap.com.br/"
USERNAME  = "pf2062"            # ajuste para o seu usuário
PASSWORD  = "Svp0rt3@T!789"     # ajuste para a sua senha
DB_FILE   = "atividades.db"

HEADLESS  = True                # <<<<<<  Mude para False se quiser ver o Chrome
# --------------------------------------------------------------------------- #


def iniciar_navegador(headless: bool = True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=opts)


def somente_texto(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n").strip()


def executar(sql: str, params=(), fetch=False):
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall() if fetch else None


def inicializar_banco():
    executar("""CREATE TABLE IF NOT EXISTS atividades(
                 id INTEGER PRIMARY KEY,
                 turma TEXT, fase TEXT, id_atividade TEXT,
                 nome_atividade TEXT, url TEXT)""")
    executar("""CREATE TABLE IF NOT EXISTS alunos(
                 id INTEGER PRIMARY KEY,
                 id_atividade TEXT, id_aluno TEXT, rm TEXT, nome TEXT, grupo TEXT,
                 nota TEXT, feedback TEXT)""")


# -------------------------- MOODLE HELPERS --------------------------------- #
def logar_moodle(drv):
    drv.get(LOGIN_URL)
    WebDriverWait(drv, 10).until(
        EC.presence_of_element_located((By.ID, "username")))
    drv.find_element(By.ID, "username").send_keys(USERNAME)
    drv.find_element(By.ID, "password").send_keys(PASSWORD + Keys.RETURN)
    WebDriverWait(drv, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "body")))


def capturar_nome_atividade(drv, url):
    drv.get(url)
    time.sleep(2)
    try:
        return drv.find_element(By.CSS_SELECTOR,
                                "div.page-header-headings h1").text.strip()
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
        WebDriverWait(drv, 8).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "#id_assignfeedbackcomments_editor_ifr,"
                "#id_assignfeedbackcomments_editor")))
        if drv.find_elements(By.ID, "id_assignfeedbackcomments_editor_ifr"):
            iframe = drv.find_element(By.ID,
                                      "id_assignfeedbackcomments_editor_ifr")
            drv.switch_to.frame(iframe)
            fb_raw = drv.find_element(By.CSS_SELECTOR,
                                      "body#tinymce").get_attribute("innerHTML")
            drv.switch_to.default_content()
        else:
            el = drv.find_element(By.ID,
                                  "id_assignfeedbackcomments_editor")
            fb_raw = (el.get_attribute("value")
                      if el.tag_name.lower() == "textarea"
                      else el.get_attribute("innerHTML"))
    except:
        pass

    return nota, somente_texto(fb_raw)


def listar_basico(drv, id_atividade):
    drv.get(f"https://on.fiap.com.br/mod/assign/view.php?id={id_atividade}&action=grading")
    time.sleep(3)
    try:
        drv.find_element(By.LINK_TEXT, "Todos").click()
        time.sleep(2)
    except:
        pass
    soup = BeautifulSoup(drv.page_source, "html.parser")
    alunos = []
    for tr in soup.select("table tbody tr"):
        chk = tr.select_one('input[name="selectedusers"]')
        if not chk:
            continue
        alunos.append({
            "id_aluno": chk["value"].strip(),
            "rm": tr.select_one("td.c4.username").text.strip(),
            "nome": tr.select_one("td.c2").text.strip(),
            "grupo": tr.select_one("td.c6").text.strip() if tr.select_one("td.c6") else "",
            "nota": "",
            "feedback": ""
        })
    return alunos


def listar_completo(drv, id_atividade):
    drv.get(f"https://on.fiap.com.br/mod/assign/view.php?id={id_atividade}&action=grading")
    time.sleep(3)
    try:
        drv.find_element(By.LINK_TEXT, "Todos").click()
        time.sleep(2)
    except:
        pass
    soup = BeautifulSoup(drv.page_source, "html.parser")
    alunos = []
    for tr in soup.select("table tbody tr"):
        chk = tr.select_one('input[name="selectedusers"]')
        if not chk:
            continue
        id_aluno = chk["value"].strip()
        nota, fb = obter_nota_feedback(drv, id_atividade, id_aluno)
        alunos.append({
            "id_aluno": id_aluno,
            "rm": tr.select_one("td.c4.username").text.strip(),
            "nome": tr.select_one("td.c2").text.strip(),
            "grupo": tr.select_one("td.c6").text.strip() if tr.select_one("td.c6") else "",
            "nota": nota,
            "feedback": fb
        })
    return alunos


# ---------- escrever_feedback e salvar_grade (iguais às versões anteriores) #
def escrever_feedback(drv, texto):
    if drv.find_elements(By.ID, "id_assignfeedbackcomments_editor_ifr"):
        ifr = drv.find_element(By.ID, "id_assignfeedbackcomments_editor_ifr")
        drv.switch_to.frame(ifr)
        drv.execute_script("document.body.innerHTML = arguments[0];",
                           texto.replace("\n", "<br>"))
        drv.switch_to.default_content()
    else:
        el = drv.find_element(By.ID, "id_assignfeedbackcomments_editor")
        tag = el.tag_name.lower()
        try:
            if tag == "textarea":
                el.clear()
                el.send_keys(texto)
            else:
                el.send_keys(Keys.CONTROL + "a")
                el.send_keys(texto)
        except ElementNotInteractableException:
            if tag == "textarea":
                drv.execute_script("arguments[0].value = arguments[1];", el, texto)
            else:
                drv.execute_script("arguments[0].innerText = arguments[1];", el, texto)


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
            btn = drv.find_element(by, val)
            break
        except:
            pass
    if btn is None:
        raise RuntimeError("Botão 'Salvar mudanças' não encontrado.")
    drv.execute_script("arguments[0].scrollIntoView(true);", btn)
    btn.click()
    end = time.time() + 15
    while time.time() < end:
        try:
            if drv.find_elements(By.CSS_SELECTOR, ".alert-success"):
                return
            if not btn.is_enabled() or btn.get_attribute("disabled"):
                return
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
        ["Inserir Nova Atividade", "Visualizar Atividades", "Editar Notas e Feedbacks"]
    )

    # -------------------- INSERIR ---------------------------------------- #
    if menu == "Inserir Nova Atividade":
        url   = st.text_input("URL da atividade:")
        fase  = st.text_input("Fase (ex: Capítulo 1):")
        turma = st.text_input("Turma (ex: 2A, 3B):")
        col1, col2 = st.columns(2)
        modo = None
        if col1.button("Capturar rápido (só alunos)"):
            modo = "basico"
        if col2.button("Capturar completo (alunos + notas + feedback)"):
            modo = "completo"

        if modo and url and fase and turma:
            id_atv = urlparse(url).query.split("id=")[1].split("&")[0]
            drv = iniciar_navegador(headless=HEADLESS)
            try:
                logar_moodle(drv)
                nome = capturar_nome_atividade(drv, url)
                alunos = listar_completo(drv, id_atv) if modo == "completo" else listar_basico(drv, id_atv)

                executar("""INSERT INTO atividades(turma, fase, id_atividade, nome_atividade, url)
                            VALUES(?,?,?,?,?)""", (turma, fase, id_atv, nome, url))
                for a in alunos:
                    executar("""INSERT INTO alunos(
                        id_atividade, id_aluno, rm, nome, grupo, nota, feedback)
                        VALUES(?,?,?,?,?,?,?)""",
                             (id_atv, a["id_aluno"], a["rm"], a["nome"],
                              a["grupo"], a["nota"], a["feedback"]))
                st.success(f"Cadastrados {len(alunos)} alunos "
                           f"({'completos' if modo == 'completo' else 'básicos'}).")
            finally:
                drv.quit()

    # -------------------- VISUALIZAR ------------------------------------ #
    elif menu == "Visualizar Atividades":
        turmas = executar("SELECT DISTINCT turma FROM atividades", fetch=True)
        if not turmas:
            st.info("Nenhuma atividade."); return
        turma_sel = st.selectbox("Turma", [t[0] for t in turmas])
        fases = executar("SELECT DISTINCT fase FROM atividades WHERE turma=?",
                         (turma_sel,), fetch=True)
        if not fases:
            st.info("Sem fases."); return
        fase_sel = st.selectbox("Fase", [f[0] for f in fases])
        rows = executar("""SELECT nome_atividade, url
                           FROM atividades
                           WHERE turma=? AND fase=?""", (turma_sel, fase_sel), fetch=True)
        for n, u in rows:
            st.markdown(f"• **{n}** — [abrir]({u})")

    # -------------------- EDITAR ---------------------------------------- #
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
        atvs = executar("""SELECT id_atividade, nome_atividade
                           FROM atividades
                           WHERE turma=? AND fase=?""", (turma_sel, fase_sel), fetch=True)
        if not atvs:
            st.info("Sem atividades."); return
        atv_sel = st.selectbox("Atividade", [f"{a[0]} — {a[1]}" for a in atvs])
        id_atv = atv_sel.split(" — ")[0]

        alunos = executar("""SELECT id, id_aluno, rm, nome, grupo, nota, feedback
                             FROM alunos
                             WHERE id_atividade=?""", (id_atv,), True)
        df = pd.DataFrame(alunos,
                          columns=["id_reg", "id_aluno", "rm", "nome",
                                   "grupo", "nota", "feedback"])
        df["Sel"] = False
        if st.checkbox("Selecionar todos"):
            df["Sel"] = True
        edit = st.data_editor(
            df[["Sel", "id_aluno", "rm", "nome", "grupo", "nota", "feedback"]],
            num_rows="fixed", use_container_width=True)

        # IMPORTAR ------------------------------------------------------- #
        if st.button("Importar do Moodle (somente selecionados)"):
            drv = iniciar_navegador(headless=HEADLESS)
            try:
                logar_moodle(drv)
                for _, r in edit.iterrows():
                    if not r["Sel"]:
                        continue
                    id_aluno = str(r["id_aluno"])
                    id_reg = int(df.loc[df["id_aluno"] == id_aluno, "id_reg"].values[0])
                    nota, fb = obter_nota_feedback(drv, id_atv, id_aluno)
                    executar("""UPDATE alunos SET nota=?, feedback=? WHERE id=?""",
                             (nota, fb, id_reg))
                    st.success(f"{r['nome']} importado.")
            finally:
                drv.quit()
            st.rerun()

        # SINCRONIZAR ---------------------------------------------------- #
        if st.button("Salvar Alterações (somente selecionados)"):
            drv = iniciar_navegador(headless=HEADLESS)
            try:
                logar_moodle(drv)
                for _, r in edit.iterrows():
                    if not r["Sel"]:
                        continue
                    id_aluno = str(r["id_aluno"])
                    id_reg = int(df.loc[df["id_aluno"] == id_aluno, "id_reg"].values[0])
                    nota_env = str(r["nota"]).strip()
                    fb_env = somente_texto(r["feedback"])

                    drv.get(f"https://on.fiap.com.br/mod/assign/view.php?"
                            f"id={id_atv}&rownum=0&action=grader&userid={id_aluno}")

                    WebDriverWait(drv, 8).until(
                        EC.presence_of_element_located((By.ID, "id_grade")))
                    campo = drv.find_element(By.ID, "id_grade")
                    try:
                        campo.clear()
                        campo.send_keys(nota_env)
                    except ElementNotInteractableException:
                        drv.execute_script("arguments[0].value = arguments[1];",
                                           campo, nota_env)

                    escrever_feedback(drv, fb_env)
                    salvar_grade(drv)

                    executar("""UPDATE alunos SET nota=?,feedback=? WHERE id=?""",
                             (nota_env, fb_env, id_reg))
                    st.success(f"{r['nome']} sincronizado.")
            finally:
                drv.quit()
            st.rerun()

        # SALVAR LOCAL --------------------------------------------------- #
        if st.button("Salvar Localmente (somente selecionados)"):
            for _, r in edit.iterrows():
                if not r["Sel"]:
                    continue
                id_reg = int(df.loc[df["id_aluno"] == str(r["id_aluno"]),
                                    "id_reg"].values[0])
                executar("""UPDATE alunos SET nota=?,feedback=? WHERE id=?""",
                         (r["nota"], r["feedback"], id_reg))
            st.success("Alterações locais gravadas.")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    inicializar_banco()
    main()
