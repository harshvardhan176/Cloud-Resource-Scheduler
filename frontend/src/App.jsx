import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import Operations from './pages/Operations.jsx';
import Intelligence from './pages/Intelligence.jsx';
import AWS from './pages/AWS.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/ops" replace />} />
        <Route path="ops" element={<Operations />} />
        <Route path="intelligence" element={<Intelligence />} />
        <Route path="aws" element={<AWS />} />
      </Route>
    </Routes>
  );
}
