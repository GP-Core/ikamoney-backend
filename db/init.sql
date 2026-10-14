-- Solo para probar la tubería. El modelo de datos real se diseña en T18.
-- Esta tabla se borrará cuando haya modelos reales.
CREATE TABLE IF NOT EXISTS pipeline_check (
  id INT AUTO_INCREMENT PRIMARY KEY,
  message VARCHAR(255) NOT NULL
) DEFAULT CHARSET=utf8mb4;

INSERT INTO pipeline_check (message)
VALUES ('La conexion con la base de datos funciona correctamente. Todo ok!');