/**
 * PetCare — Cliente HTTP asíncrono (SessionAuthentication + CSRF) y utilidades UI.
 */
const PetCare = (() => {
  /**
   * Obtiene el token CSRF desde la cookie `csrftoken` o desde un input oculto.
   */
  function getCsrfToken() {
    const match = document.cookie
      .split("; ")
      .find((row) => row.startsWith("csrftoken="));
    if (match) {
      return decodeURIComponent(match.split("=")[1]);
    }
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  /**
   * Convierte errores de validación de DRF en un texto legible para el usuario.
   */
  function formatDrfErrors(payload) {
    if (!payload) return "Ocurrió un error inesperado.";
    if (typeof payload === "string") return payload;
    if (payload.detail) return payload.detail;

    const mensajes = [];
    for (const [campo, valor] of Object.entries(payload)) {
      const lista = Array.isArray(valor) ? valor.join(" ") : String(valor);
      if (campo === "non_field_errors" || campo === "__all__") {
        mensajes.push(lista);
      } else {
        mensajes.push(`${campo}: ${lista}`);
      }
    }
    return mensajes.join(" | ") || "Error al procesar la solicitud.";
  }

  /**
   * Petición Fetch JSON autenticada por sesión con manejo automático de CSRF y errores.
   */
  async function apiFetch(url, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const headers = {
      Accept: "application/json",
      ...(options.headers || {}),
    };

    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }

    if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
      headers["X-CSRFToken"] = getCsrfToken();
    }

    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      method,
      headers,
    });

    if (response.status === 204) {
      return null;
    }

    let data = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      data = await response.text();
    }

    if (!response.ok) {
      const err = new Error(formatDrfErrors(data));
      err.status = response.status;
      err.payload = data;
      throw err;
    }

    return data;
  }

  /**
   * Muestra una notificación Toast flotante en esquina superior derecha.
   */
  function toast(mensaje, tipo = "success") {
    const contenedor = document.getElementById("pc-toast-container");
    if (!contenedor) return;

    const colores = {
      success: { icono: "bi-check-circle-fill", borde: "#10b981", color: "#34d399" },
      danger: { icono: "bi-exclamation-octagon-fill", borde: "#ef4444", color: "#f87171" },
      warning: { icono: "bi-exclamation-triangle-fill", borde: "#f59e0b", color: "#fbbf24" },
      info: { icono: "bi-info-circle-fill", borde: "#06b6d4", color: "#22d3ee" },
    };
    const cfg = colores[tipo] || colores.info;

    const el = document.createElement("div");
    el.className = "toast align-items-center show mb-2";
    el.style.backgroundColor = "#111827";
    el.style.border = `1px solid ${cfg.borde}`;
    el.setAttribute("role", "alert");

    el.innerHTML = `
      <div class="d-flex align-items-center p-3">
        <i class="bi ${cfg.icono} fs-5 me-2" style="color:${cfg.color};"></i>
        <div class="toast-body p-0 text-light small fw-medium flex-grow-1"></div>
        <button type="button" class="btn-close btn-close-white ms-3" data-bs-dismiss="toast" aria-label="Cerrar"></button>
      </div>
    `;
    el.querySelector(".toast-body").textContent = mensaje;
    contenedor.appendChild(el);

    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 250);
    }, 4500);
  }

  /**
   * Escapa texto para inserción segura en plantillas HTML dinámicas.
   */
  function escapeHtml(valor) {
    if (valor === null || valor === undefined) return "";
    return String(valor)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Módulo de Seguridad por Inactividad:
   * - A los 5 minutos sin actividad -> Bloqueo con PIN de 4 dígitos.
   * - A los 10 minutos sin actividad -> Cierre de sesión automático (Logout).
   */
  function initInactivityLock() {
    const TIEMPO_BLOQUEO_PIN = 5 * 60 * 1000; // 5 minutos
    const TIEMPO_DESLOGUEO = 10 * 60 * 1000;  // 10 minutos

    const overlay = document.getElementById("pc-lockscreen");
    if (!overlay) return; // Si estamos en la vista de login, no aplica

    let ultimoAcceso = Date.now();
    let pantallaBloqueada = false;

    function resetearActividad() {
      if (!pantallaBloqueada) {
        ultimoAcceso = Date.now();
      }
    }

    ["mousedown", "keydown", "mousemove", "touchstart", "scroll"].forEach((evt) => {
      window.addEventListener(evt, resetearActividad, { passive: true });
    });

    setInterval(() => {
      const inactivo = Date.now() - ultimoAcceso;

      // 10 minutos -> Deslogeo total
      if (inactivo >= TIEMPO_DESLOGUEO) {
        const logoutForm = document.getElementById("form-logout-global");
        if (logoutForm) {
          logoutForm.submit();
        } else {
          window.location.href = "/logout/";
        }
        return;
      }

      // 5 minutos -> Bloqueo con PIN
      if (inactivo >= TIEMPO_BLOQUEO_PIN && !pantallaBloqueada) {
        bloquearPantalla();
      }
    }, 2000);

    function bloquearPantalla() {
      pantallaBloqueada = true;
      overlay.classList.remove("d-none");
      const pinInput = document.getElementById("pc-pin-code");
      if (pinInput) {
        pinInput.value = "";
        setTimeout(() => pinInput.focus(), 150);
      }
      document.getElementById("pc-pin-alerta")?.classList.add("d-none");
    }

    const formDesbloqueo = document.getElementById("form-desbloquear-pin");
    if (formDesbloqueo) {
      formDesbloqueo.addEventListener("submit", async (e) => {
        e.preventDefault();
        const pinInput = document.getElementById("pc-pin-code");
        const alerta = document.getElementById("pc-pin-alerta");
        const pin = pinInput.value.trim();

        if (pin.length !== 4) {
          alerta.textContent = "El PIN debe tener exactamente 4 dígitos.";
          alerta.classList.remove("d-none");
          return;
        }

        try {
          await apiFetch("/api/seguridad/verificar-pin/", {
            method: "POST",
            body: { pin },
          });

          pantallaBloqueada = false;
          ultimoAcceso = Date.now();
          overlay.classList.add("d-none");
          toast("Pantalla desbloqueada.", "success");
        } catch (err) {
          alerta.textContent = err.message || "PIN de desbloqueo incorrecto.";
          alerta.classList.remove("d-none");
          pinInput.value = "";
          pinInput.focus();
        }
      });
    }
  }

  /**
   * Inicializa el reloj en tiempo real y el botón de colapso del sidebar.
   */
  function initShell() {
    const relojEl = document.getElementById("pc-live-clock");
    if (relojEl) {
      const actualizarReloj = () => {
        const ahora = new Date();
        const fecha = ahora.toLocaleDateString("es-CL", {
          weekday: "short",
          day: "2-digit",
          month: "short",
          year: "numeric",
        });
        const hora = ahora.toLocaleTimeString("es-CL", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
        relojEl.textContent = `${fecha} · ${hora}`;
      };
      actualizarReloj();
      setInterval(actualizarReloj, 1000);
    }

    const btnCollapse = document.getElementById("pc-sidebar-toggle");
    if (btnCollapse) {
      if (localStorage.getItem("pc_sidebar_collapsed") === "1") {
        document.body.classList.add("pc-sidebar-collapsed");
      }
      btnCollapse.addEventListener("click", () => {
        if (window.innerWidth < 992) {
          document.body.classList.toggle("pc-mobile-nav-open");
        } else {
          document.body.classList.toggle("pc-sidebar-collapsed");
          const colapsado = document.body.classList.contains("pc-sidebar-collapsed");
          localStorage.setItem("pc_sidebar_collapsed", colapsado ? "1" : "0");
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initShell();
    initInactivityLock();
  });

  return {
    apiFetch,
    toast,
    formatDrfErrors,
    escapeHtml,
    getCsrfToken,
  };
})();
