import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Outlet, useLocation } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeProvider';
import { AuthProvider } from './context/AuthProvider';
import ProtectedRoute from './components/ProtectedRoute';
import RouteErrorBoundary from './components/RouteErrorBoundary';
import LoginPage from './pages/LoginPage';
import LandingPage from './pages/LandingPage';
import TermsPage from './components/TermsPage';
import PrivacyPage from './components/PrivacyPage';
import CookiePolicyPage from './components/CookiePolicyPage';
import DesktopAccessRequired from './components/DesktopAccessRequired';
import InactivityProvider from './components/InactivityProvider';
import { useDeviceAccess } from './hooks/useDeviceAccess';
import { PublicPageTransition } from './components/PublicPageTransition';
import RevelaLoader from './components/RevelaLoader';

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

function PortalDeviceGate() {
  // Keep the portal's existing device policy without blocking the public page.
  // This still re-evaluates on rotate/resize, so no orientation is stuck.
  const { restricted } = useDeviceAccess();
  return restricted ? <DesktopAccessRequired /> : <Outlet />;
}

export default function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <BrowserRouter>
          {/* Inside the router so route changes count as activity. */}
          <InactivityProvider>
            <PublicPageTransition>
            <PathnameKeyedRouteErrorBoundary>
              <Suspense
                fallback={<RevelaLoader message="Loading page…" />}
              >
                <Routes>
                  {/* Public & Legal */}
                  <Route path="/" element={<LandingPage />} />
                  <Route path="/terms" element={<TermsPage />} />
                  <Route path="/privacy" element={<PrivacyPage />} />
                  <Route path="/cookies" element={<CookiePolicyPage />} />
                  <Route path="/cookie-policy" element={<CookiePolicyPage />} />

                  {/* Login and protected screens retain the existing device policy. */}
                  <Route element={<PortalDeviceGate />}>
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/home" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
                    <Route path="/map" element={<ProtectedRoute><MapPage /></ProtectedRoute>} />
                    <Route path="/registry" element={<ProtectedRoute><RegistryPage /></ProtectedRoute>} />
                    <Route path="/analytics" element={<ProtectedRoute><AnalyticsPage /></ProtectedRoute>} />
                    <Route path="/inspections/calendar" element={<ProtectedRoute><InspectionCalendarPage /></ProtectedRoute>} />
                    <Route path="/inspections" element={<ProtectedRoute><InspectionPage /></ProtectedRoute>} />
                    <Route path="/users" element={<ProtectedRoute><UserManagementPage /></ProtectedRoute>} />
                    <Route path="/reports" element={<ProtectedRoute><ExportReportsPage /></ProtectedRoute>} />
                    <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
                  </Route>
                </Routes>
              </Suspense>
            </PathnameKeyedRouteErrorBoundary>
            </PublicPageTransition>
          </InactivityProvider>
        </BrowserRouter>
      </ThemeProvider>
    </AuthProvider>
  );
}
