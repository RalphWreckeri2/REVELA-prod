import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeProvider';
import { AuthProvider } from './context/AuthProvider';
import ProtectedRoute from './components/ProtectedRoute';   // ← add this
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import MapPage from './pages/MapPage';
import RegistryPage from './pages/RegistryPage';
import AnalyticsPage from './pages/AnalyticsPage';
import InspectionPage from './pages/InspectionPage';
import InspectionCalendarPage from './pages/InspectionCalendarPage';
import UserManagementPage from './pages/UserManagementPage';
import ExportReportsPage from './pages/ExportReportsPage';
import SettingsPage from './pages/SettingsPage';
import TermsPage from './components/TermsPage';
import PrivacyPage from './components/PrivacyPage';
import CookiePolicyPage from './components/CookiePolicyPage';
import DesktopAccessRequired from './components/DesktopAccessRequired';
import InactivityProvider from './components/InactivityProvider';
import { isMobileBrowser } from './components/mobileDetection';

export default function App() {
  if (isMobileBrowser()) {
    return <DesktopAccessRequired />;
  }

  return (
    <AuthProvider>
      <ThemeProvider>
        <BrowserRouter>
          {/* Inside the router so route changes count as activity. */}
          <InactivityProvider>
          <Routes>
            {/* Public & Legal */}
            <Route path="/" element={<LoginPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/cookies" element={<CookiePolicyPage />} />
            <Route path="/cookie-policy" element={<CookiePolicyPage />} />

            {/* Protected */}
            <Route path="/home" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
            <Route path="/map" element={<ProtectedRoute><MapPage /></ProtectedRoute>} />
            <Route path="/registry" element={<ProtectedRoute><RegistryPage /></ProtectedRoute>} />
            <Route path="/analytics" element={<ProtectedRoute><AnalyticsPage /></ProtectedRoute>} />
            <Route path="/inspections/calendar" element={<ProtectedRoute><InspectionCalendarPage /></ProtectedRoute>} />
            <Route path="/inspections" element={<ProtectedRoute><InspectionPage /></ProtectedRoute>} />
            <Route path="/users" element={<ProtectedRoute><UserManagementPage /></ProtectedRoute>} />
            <Route path="/reports" element={<ProtectedRoute><ExportReportsPage /></ProtectedRoute>} />
            <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
          </Routes>
          </InactivityProvider>
        </BrowserRouter>
      </ThemeProvider>
    </AuthProvider>
  );
}