import "./widget.css";

(function () {
  let config = null;
  let sessionId = null;

  function createUuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function init(userConfig) {
    if (config) return;
    config = userConfig || {};
    sessionId = config.sessionId || createUuid();
    renderBubble();
    renderPanel();
  }

  function renderBubble() {
    const bubble = document.createElement("div");
    bubble.id = "flyme-chat-bubble";
    bubble.onclick = () => togglePanel(true);
    document.body.appendChild(bubble);
  }

  function renderPanel() {
    const panel = document.createElement("div");
    panel.id = "flyme-chat-panel";
    panel.classList.add("flyme-chat-hidden");
    panel.innerHTML = `
      <div class="flyme-chat-header">
        <span class="flyme-chat-title">Fly Me Assistant</span>
        <button class="flyme-chat-close">&times;</button>
      </div>
      <div class="flyme-chat-messages"></div>
      <div class="flyme-chat-typing" style="display:none;">
        <span>Assistant en train de comprendre…</span>
      </div>
      <div class="flyme-chat-input">
        <textarea placeholder="Décris ton voyage…"></textarea>
        <button class="flyme-chat-send">Envoyer</button>
      </div>
    `;
    document.body.appendChild(panel);

    panel
      .querySelector(".flyme-chat-close")
      .addEventListener("click", () => togglePanel(false));

    panel
      .querySelector(".flyme-chat-send")
      .addEventListener("click", handleSend);

    panel
      .querySelector("textarea")
      .addEventListener("keydown", e => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          handleSend();
        }
      });

    if (config.welcomeMessage) {
      appendBotMessage(config.welcomeMessage);
    }
  }

  function togglePanel(open) {
    const panel = document.getElementById("flyme-chat-panel");
    if (!panel) return;
    if (open) {
      panel.classList.remove("flyme-chat-hidden");
    } else {
      panel.classList.add("flyme-chat-hidden");
    }
  }

  function appendUserMessage(text) {
    const container = document.querySelector(".flyme-chat-messages");
    const el = document.createElement("div");
    el.className = "flyme-chat-message flyme-chat-message-user";
    el.textContent = text;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
  }

  function appendBotMessage(text) {
    const container = document.querySelector(".flyme-chat-messages");
    const el = document.createElement("div");
    el.className = "flyme-chat-message flyme-chat-message-bot";
    el.textContent = text;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
  }

  function setTyping(visible) {
    const typing = document.querySelector(".flyme-chat-typing");
    if (!typing) return;
    typing.style.display = visible ? "block" : "none";
  }

  async function handleSend() {
    const panel = document.getElementById("flyme-chat-panel");
    const textarea = panel.querySelector("textarea");
    const text = textarea.value.trim();
    if (!text) return;

    textarea.value = "";
    appendUserMessage(text);
    setTyping(true);

    try {
      // ✅ MODIFICATION : Utilisation d'un chemin relatif pour éviter les erreurs d'IP
      const res = await fetch("/v1/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          text: text
        })
      });

      if (!res.ok) throw new Error("Erreur serveur");

      const data = await res.json();
      setTyping(false);

      if (data && data.text) {
        appendBotMessage(data.text);
      } else {
        appendBotMessage("Réponse inattendue du serveur.");
      }
    } catch (e) {
      console.error("Erreur détaillée:", e);
      setTyping(false);
      appendBotMessage(
        "Erreur réseau ou backend indisponible. Vérifie ta connexion."
      );
    }
  }

  window.FlyMeChat = {
    init,
    open: () => togglePanel(true),
    close: () => togglePanel(false),
    destroy: () => {
      document.getElementById("flyme-chat-bubble")?.remove();
      document.getElementById("flyme-chat-panel")?.remove();
      config = null;
      sessionId = null;
    },
    getSessionId: () => sessionId
  };
})();