const navToggle = document.getElementById("nav-toggle");
const navBackdrop = document.getElementById("nav-backdrop");
const navigation = document.getElementById("navigation");
const navToggleIcon = navToggle ? navToggle.querySelector("i") : null;
const mobileNavQuery = window.matchMedia("(max-width: 768px)");

function setNavOpen(open) {
    document.body.classList.toggle("nav-open", open);
    if (navToggle) {
        navToggle.setAttribute("aria-expanded", open ? "true" : "false");
        navToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    }
    if (navToggleIcon) {
        navToggleIcon.classList.toggle("fa-bars", !open);
        navToggleIcon.classList.toggle("fa-xmark", open);
    }
}

function closeNav() {
    setNavOpen(false);
}

if (navToggle && navigation) {
    navToggle.addEventListener("click", () => {
        setNavOpen(!document.body.classList.contains("nav-open"));
    });

    if (navBackdrop) {
        navBackdrop.addEventListener("click", closeNav);
    }

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeNav();
        }
    });

    navigation.addEventListener("click", (event) => {
        if (event.target.closest("a")) {
            closeNav();
        }
    });

    const handleViewportChange = () => {
        if (!mobileNavQuery.matches) {
            closeNav();
        }
    };

    if (typeof mobileNavQuery.addEventListener === "function") {
        mobileNavQuery.addEventListener("change", handleViewportChange);
    } else if (typeof mobileNavQuery.addListener === "function") {
        mobileNavQuery.addListener(handleViewportChange);
    }
}
