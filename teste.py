import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configurações
USERNAME = "pf2062"
PASSWORD = "Svp0rt3@T!789"
URL_LOGIN = "https://on.fiap.com.br/login/index.php"
URL_LANCAMENTO = "https://on.fiap.com.br/mod/assign/view.php?id=477189&rownum=0&action=grader&userid=912330"


def iniciar_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    return driver


def login(driver):
    driver.get(URL_LOGIN)
    time.sleep(2)

    usuario_input = driver.find_element(By.ID, "username")
    usuario_input.send_keys(USERNAME)

    senha_input = driver.find_element(By.ID, "password")
    senha_input.send_keys(PASSWORD)
    senha_input.send_keys(Keys.RETURN)

    WebDriverWait(driver, 10).until(EC.url_changes(URL_LOGIN))
    print("Login feito com sucesso.")


def lancar_nota_comentario(driver, nota, comentario):
    driver.get(URL_LANCAMENTO)
    time.sleep(2)

    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "id_grade")))

    campo_nota = driver.find_element(By.ID, "id_grade")
    campo_nota.clear()
    campo_nota.send_keys(str(nota))

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "id_assignfeedbackcomments_editor_ifr")))

        # Entra no iframe do editor
        iframe = driver.find_element(By.ID, "id_assignfeedbackcomments_editor_ifr")
        driver.switch_to.frame(iframe)

        # Preenche o tinymce
        campo_comentario = driver.find_element(By.ID, "tinymce")
        campo_comentario.clear()
        campo_comentario.send_keys(comentario)

        # Sai do iframe
        driver.switch_to.default_content()

        # **FORÇA o tinymce a salvar no textarea invisível**
        driver.execute_script("tinyMCE.get('id_assignfeedbackcomments_editor').save();")

    except Exception as e:
        print(f"Erro ao preencher comentário: {e}")
        driver.switch_to.default_content()

    # Clica no botão salvar mudanças
    WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.NAME, "savechanges")))
    botao_salvar = driver.find_element(By.NAME, "savechanges")
    botao_salvar.click()

    print("Nota e comentário lançados e salvos com sucesso.")


if __name__ == "__main__":
    driver = iniciar_driver()
    try:
        login(driver)
        lancar_nota_comentario(driver, nota=1, comentario="teste")
    finally:
        time.sleep(5)
        driver.quit()
