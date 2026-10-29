import { Navigate, Route, Routes } from 'react-router-dom';
import LoginPage from '../pages/Login/LoginPage.jsx';
import ClientReportsPage from '../pages/ClientReports/ClientReportsPage.jsx';
import CalculatorPage from '../pages/Calculator/CalculatorPage.jsx';
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
        <Route path="/calculators" element={<CalculatorPage />} />
        <Route path="/mutual-fund" element={<ComingSoonPage title="Mutual Fund" />} />
      </Route>
      <Route path="*" element={<Navigate to="/client-reports" replace />} />
    </Routes>
  );
}
