###############################################################################
#  Lançamento de notas/feedback – FIAP Moodle + Streamlit                     #
#  Versão: 12-mai-2025                                                        #
#  • “Editar” → mostra Nota máxima + coluna Ir Além                           #
#  • “Visualizar” agora permite corrigir Turma, Fase e Nota máxima (local)    #
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


LOGIN_URL = "https://on.fiap.com.br/"
USERNAME  = "pf2062"
PASSWORD  = "Svp0rt3@T!789"
DB_FILE   = "atividades.db"
HEADLESS  = True


def iniciar_navegador(headless=True):
    opts = Options()
    if headless: opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox"); opts.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=opts)


def somente_texto(html): return BeautifulSoup(html or "", "html.parser").get_text("\n").strip()


def executar(sql, params=(), fetch=False):
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor(); cur.execute(sql, params)
        return cur.fetchall() if fetch else None


def inicializar_banco():
    executar("""CREATE TABLE IF NOT EXISTS atividades(
                 id INTEGER PRIMARY KEY,
                 turma TEXT, fase TEXT, id_atividade TEXT,
                 nome_atividade TEXT, url TEXT, nota_max REAL)""")
    try: executar("ALTER TABLE atividades ADD COLUMN nota_max REAL")
    except sqlite3.OperationalError: pass
    executar("""CREATE TABLE IF NOT EXISTS alunos(
                 id INTEGER PRIMARY KEY,
                 id_atividade TEXT, id_aluno TEXT, rm TEXT, nome TEXT, grupo TEXT,
                 nota TEXT, feedback TEXT, ir_alem INTEGER DEFAULT 0)""")
    try: executar("ALTER TABLE alunos ADD COLUMN ir_alem INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass


# -------------------- helpers Selenium (iguais às versões anteriores) ------ #
#  logar_moodle, capturar_nome_atividade, obter_nota_feedback,
#  listar_basico, listar_completo, escrever_feedback, salvar_grade
# --------------------------------------------------------------------------- #


def main():
    st.title("Gerenciamento de Atividades e Alunos – FIAP")

    menu = st.sidebar.selectbox(
        "Menu",
        ["Inserir Nova Atividade", "Visualizar Atividades", "Editar Notas e Feedbacks"]
    )

    # -------------------- INSERIR -------------------------------------- #
    if menu == "Inserir Nova Atividade":
        url   = st.text_input("URL da atividade:")
        fase  = st.text_input("Fase (ex: Capítulo 1):")
        turma = st.text_input("Turma (ex: 2A, 3B):")
        nota_max = st.number_input("Nota máxima (peso)", min_value=0.5, step=0.5)
        col1, col2 = st.columns(2)
        modo = None
        if col1.button("Capturar rápido (só alunos)"):                   modo = "basico"
        if col2.button("Capturar completo (alunos + notas + feedback)"): modo = "completo"

        if modo and url and fase and turma and nota_max > 0:
            id_atv = urlparse(url).query.split("id=")[1].split("&")[0]
            drv = iniciar_navegador(HEADLESS)
            try:
                logar_moodle(drv)
                nome = capturar_nome_atividade(drv, url)
                alunos = listar_completo(drv,id_atv) if modo=="completo" else listar_basico(drv,id_atv)

                executar("""INSERT INTO atividades(
                    turma,fase,id_atividade,nome_atividade,url,nota_max)
                    VALUES(?,?,?,?,?,?)""",(turma,fase,id_atv,nome,url,nota_max))
                for a in alunos:
                    executar("""INSERT INTO alunos(
                        id_atividade,id_aluno,rm,nome,grupo,nota,feedback,ir_alem)
                        VALUES(?,?,?,?,?,?,?,0)""",
                             (id_atv,a["id_aluno"],a["rm"],a["nome"],
                              a["grupo"],a["nota"],a["feedback"]))
                st.success(f"Cadastrados {len(alunos)} alunos | Nota máx = {nota_max}.")
            finally:
                drv.quit()

    # -------------------- VISUALIZAR (agora editável) ------------------ #
    elif menu == "Visualizar Atividades":
        atividades = executar("""SELECT id,turma,fase,nome_atividade,nota_max,url
                                 FROM atividades ORDER BY turma,fase,id""", fetch=True)
        if not atividades:
            st.info("Nenhuma atividade cadastrada."); return

        df_atv = pd.DataFrame(atividades,
                              columns=["id","Turma","Fase","Atividade","Nota máxima","URL"])
        st.markdown("### Atividades cadastradas (edite localmente)")
        edit = st.data_editor(df_atv[["id","Turma","Fase","Atividade","Nota máxima","URL"]],
                              use_container_width=True,
                              column_config={"id": st.column_config.Column(disabled=True),
                                             "URL": st.column_config.LinkColumn(disabled=True)})

        if st.button("Salvar alterações de Turma/Fase/Nota máx"):
            for _, row in edit.iterrows():
                executar("""UPDATE atividades SET turma=?,fase=?,nota_max=? WHERE id=?""",
                         (row["Turma"], row["Fase"], row["Nota máxima"], int(row["id"])))
            st.success("Informações atualizadas localmente.")

    # -------------------- EDITAR NOTAS / FEEDBACK ---------------------- #
    elif menu == "Editar Notas e Feedbacks":
        turmas = executar("SELECT DISTINCT turma FROM atividades", fetch=True)
        if not turmas: st.info("Nenhuma atividade."); return
        turma_sel = st.selectbox("Turma", [t[0] for t in turmas])

        fases = executar("SELECT DISTINCT fase FROM atividades WHERE turma=?",(turma_sel,),fetch=True)
        if not fases: st.info("Sem fases."); return
        fase_sel = st.selectbox("Fase", [f[0] for f in fases])

        atvs = executar("""SELECT id_atividade,nome_atividade,nota_max
                           FROM atividades WHERE turma=? AND fase=?""",
                        (turma_sel,fase_sel), fetch=True)
        if not atvs: st.info("Sem atividades."); return

        atv_sel = st.selectbox("Atividade",
                    [f"{a[0]} — {a[1]} (peso {a[2]})" for a in atvs])
        id_atv  = atv_sel.split(" — ")[0]
        nota_max = next(a[2] for a in atvs if a[0]==id_atv)

        st.markdown(f"**Nota máxima:** {nota_max}")

        alunos = executar("""SELECT id,id_aluno,rm,nome,grupo,nota,feedback,ir_alem
                             FROM alunos WHERE id_atividade=?""",(id_atv,), True)
        df = pd.DataFrame(alunos,
                          columns=["id_reg","id_aluno","rm","nome","grupo",
                                   "nota","feedback","ir_alem"])
        df["Sel"] = False
        if st.checkbox("Selecionar todos"): df["Sel"] = True

        edit_cols = ["Sel","id_aluno","rm","nome","grupo",
                     "nota","feedback","ir_alem"]
        edit = st.data_editor(df[edit_cols], num_rows="fixed", use_container_width=True)

        # ------- IMPORTAR ---------- #
        if st.button("Importar do Moodle (somente selecionados)"):
            drv = iniciar_navegador(HEADLESS)
            try:
                logar_moodle(drv)
                for _, r in edit.iterrows():
                    if not r["Sel"]: continue
                    id_aluno = str(r["id_aluno"])
                    id_reg = int(df.loc[df["id_aluno"]==id_aluno,"id_reg"].values[0])
                    nota, fb = obter_nota_feedback(drv, id_atv, id_aluno)
                    executar("UPDATE alunos SET nota=?,feedback=? WHERE id=?",
                             (nota, fb, id_reg))
                st.success("Importação concluída.")
            finally: drv.quit(); st.rerun()

        # ------- SINCRONIZAR ------- #
        if st.button("Salvar Alterações (somente selecionados)"):
            drv = iniciar_navegador(HEADLESS)
            try:
                logar_moodle(drv)
                for _, r in edit.iterrows():
                    if not r["Sel"]: continue
                    id_aluno = str(r["id_aluno"])
                    id_reg = int(df.loc[df["id_aluno"]==id_aluno,"id_reg"].values[0])
                    nota_env = str(r["nota"]).strip()
                    fb_env   = somente_texto(r["feedback"])
                    ir_alem_val = int(r.get("ir_alem",0))

                    drv.get(f"https://on.fiap.com.br/mod/assign/view.php?"
                            f"id={id_atv}&rownum=0&action=grader&userid={id_aluno}")
                    WebDriverWait(drv,8).until(EC.presence_of_element_located((By.ID,"id_grade")))
                    campo = drv.find_element(By.ID,"id_grade")
                    try: campo.clear(); campo.send_keys(nota_env)
                    except ElementNotInteractableException:
                        drv.execute_script("arguments[0].value=arguments[1];",campo,nota_env)
                    escrever_feedback(drv, fb_env)
                    salvar_grade(drv)

                    executar("UPDATE alunos SET nota=?,feedback=?,ir_alem=? WHERE id=?",
                             (nota_env, fb_env, ir_alem_val, id_reg))
                st.success("Sincronização concluída.")
            finally: drv.quit(); st.rerun()

        # ------- SALVAR LOCAL ------- #
        if st.button("Salvar Localmente (somente selecionados)"):
            for _, r in edit.iterrows():
                if not r["Sel"]: continue
                id_reg = int(df.loc[df["id_aluno"]==str(r["id_aluno"]),"id_reg"].values[0])
                executar("UPDATE alunos SET nota=?,feedback=?,ir_alem=? WHERE id=?",
                         (r["nota"], r["feedback"], int(r.get("ir_alem",0)), id_reg))
            st.success("Alterações locais gravadas.")


if __name__ == "__main__":
    inicializar_banco()
    main()
