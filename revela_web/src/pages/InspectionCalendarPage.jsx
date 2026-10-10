import { useContext } from "react";
import { Link, useSearchParams } from "react-router-dom";
import DashboardLayout from "../components/DashboardLayout";
import Footer from "../components/Footer";
import InspectionCalendar from "../components/InspectionCalendar";
import { AuthContext } from "../context/authContext";

const isValidDate = (value) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return (
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
  );
};

export default function InspectionCalendarPage() {
  const { token, user } = useContext(AuthContext);
  const [searchParams] = useSearchParams();
  const requestedDate = searchParams.get("date");
  const initialDate = isValidDate(requestedDate) ? requestedDate : undefined;

  return (
    <DashboardLayout
      user={{ initials: user?.fullName?.charAt(0) ?? "?", name: user?.fullName ?? "" }}
    >
      <header className="inspection-calendar-page-header">
        <div className="inspection-calendar-page-header-text">
          <Link className="inspection-calendar-back" to="/inspections">
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
            Back to Dispatch
          </Link>
          <h1 className="page-title">Inspection Calendar</h1>
          <p className="page-subtitle">
            Review recorded inspection activity by date.
          </p>
        </div>
      </header>

      <InspectionCalendar token={token} initialDate={initialDate} />

      <Footer />
    </DashboardLayout>
  );
}
