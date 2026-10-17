import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeProvider';
import { AuthProvider } from './context/AuthProvider';
import ProtectedRoute from './components/ProtectedRoute';   // ← add this
import RouteErrorBoundary from './components/RouteErrorBoundary';
import LoginPage from './pages/LoginPage';
import TermsPage from './components/TermsPage';
import PrivacyPage from './components/PrivacyPage';
import CookiePolicyPage from './components/CookiePolicyPage';
import DesktopAccessRequired from './components/DesktopAccessRequired';
import InactivityProvider from './components/InactivityProvider';
import { useDeviceAccess } from './hooks/useDeviceAccess';

const HomePage = lazy(() => import('./pages/HomePage'));
const MapPage = lazy(() => import('./pages/MapPage'));
const RegistryPage = lazy(() => import('./pages/RegistryPage'));
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const InspectionPage = lazy(() => import('./pages/InspectionPage'));
const InspectionCalendarPage = lazy(() => import('./pages/InspectionCalendarPage'));
const UserManagementPage = lazy(() => import('./pages/UserManagementPage'));
const ExportReportsPage = lazy(() => import('./pages/ExportReportsPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

function PathnameKeyedRouteErrorBoundary({ children }) {
  const { pathname } = useLocation();
  return <RouteErrorBoundary key={pathname}>{children}</RouteErrorBoundary>;
}

export default function App() {
  // Usability gate only: phone-sized screens get the restricted-access notice.
  // Tablets, laptops and desktops fall through to the normal application.
  // This re-evaluates on rotate/resize, so no orientation is stuck.
  const { restricted } = useDeviceAccess();

  if (restricted) {
    return <DesktopAccessRequired />;
  }

  return (
    <AuthProvider>
      <ThemeProvider>
        <BrowserRouter>
          {/* Inside the router so route changes count as activity. */}
          <InactivityProvider>
          <PathnameKeyedRouteErrorBoundary>
          <Suspense
            fallback={(
              <div className="route-loading" role="status">
                <span className="route-loading-indicator" aria-hidden="true" />
                Loading page...
              </div>
            )}
          >
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
          </Suspense>
          </PathnameKeyedRouteErrorBoundary>
          </InactivityProvider>
        </BrowserRouter>
      </ThemeProvider>
    </AuthProvider>
  );
}