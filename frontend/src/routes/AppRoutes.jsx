import { Navigate, Route, Routes } from 'react-router-dom';
import LoginPage from '../pages/Login/LoginPage.jsx';
import ClientReportsPage from '../pages/ClientReports/ClientReportsPage.jsx';
import ClientPlanPage from '../pages/ClientReports/ClientPlan/ClientPlanPage.jsx';
import ComingSoonPage from '../pages/Placeholder/ComingSoonPage.jsx';
import AppLayout from '../components/layout/AppLayout.jsx';
import ProtectedRoute from './ProtectedRoute.jsx';

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/client-reports" element={<ClientReportsPage />} />
        <Route path="/client-reports/:id" element={<ClientPlanPage />} />
        <Route path="/calculators" element={<ComingSoonPage title="Calculators" />} />
        <Route path="/mutual-fund" element={<ComingSoonPage title="Mutual Fund" />} />
      </Route>
      <Route path="*" element={<Navigate to="/client-reports" replace />} />
    </Routes>
  );
}
