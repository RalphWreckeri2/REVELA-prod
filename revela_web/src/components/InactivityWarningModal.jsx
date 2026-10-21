import { useEffect } from "react";
import Swal from "sweetalert2";

/**
 * Shown at 9 minutes of inactivity. Activity closes the alert without logging
 * out; otherwise the user must choose to stay or will be logged out at 10 min.
 */
export default function InactivityWarningModal({ onStayLoggedIn, onLogout }) {
  useEffect(() => {
    let active = true;

    Swal.fire({
      icon: "warning",
      title: "Session About to Expire",
      text: "Your session is about to expire due to inactivity. You will be automatically logged out in 1 minute.",
      showDenyButton: true,
      confirmButtonText: "Stay Logged In",
      denyButtonText: "Log Out Now",
      confirmButtonColor: "#56ab2f",
      denyButtonColor: "#ef4444",
      allowOutsideClick: false,
      allowEscapeKey: false,
      timer: 60_000,
      timerProgressBar: true,
      focusConfirm: true,
    }).then((result) => {
      if (!active) return;
      if (result.isConfirmed) {
        onStayLoggedIn();
      } else if (
        result.isDenied ||
        result.dismiss === Swal.DismissReason.timer
      ) {
        onLogout();
      }
    });

    return () => {
      active = false;
      Swal.close();
    };
  }, [onLogout, onStayLoggedIn]);

  return null;
}
