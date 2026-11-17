-- IKAMONEY · Esquema inicial (migración 0001) · MySQL 8
-- REFERENCIA de solo lectura, generada desde la misma definición que la migración.
-- Para crear la base de verdad usa:  alembic upgrade head  (ver README).

SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE `usuario` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) NOT NULL,
  `correo` VARCHAR(255) NOT NULL,
  `contrasena_hash` VARCHAR(255) NOT NULL,
  `moneda` CHAR(3) NOT NULL DEFAULT 'MXN',
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_usuario_correo` (`correo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `categoria` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NULL,
  `nombre` VARCHAR(60) NOT NULL,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_categoria_usuario_nombre` (`usuario_id`, `nombre`),
  CONSTRAINT `fk_categoria_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `ingreso` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `descripcion` VARCHAR(120) NOT NULL,
  `monto` DECIMAL(12,2) NOT NULL,
  `frecuencia` ENUM('unico', 'semanal', 'quincenal', 'mensual', 'anual') NOT NULL,
  `fecha_inicio` DATE NOT NULL,
  `fecha_fin` DATE NULL,
  `activo` TINYINT(1) NOT NULL DEFAULT 1,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_ingreso_usuario_id` (`usuario_id`),
  CONSTRAINT `fk_ingreso_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_ingreso_monto_positivo` CHECK (monto > 0),
  CONSTRAINT `ck_ingreso_fechas_validas` CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `gasto` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `categoria_id` BIGINT UNSIGNED NOT NULL,
  `descripcion` VARCHAR(120) NOT NULL,
  `tipo` ENUM('fijo', 'variable') NOT NULL,
  `monto` DECIMAL(12,2) NOT NULL,
  `frecuencia` ENUM('unico', 'semanal', 'quincenal', 'mensual', 'anual') NOT NULL,
  `fecha_inicio` DATE NOT NULL,
  `fecha_fin` DATE NULL,
  `activo` TINYINT(1) NOT NULL DEFAULT 1,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_gasto_usuario_id` (`usuario_id`),
  KEY `ix_gasto_categoria_id` (`categoria_id`),
  CONSTRAINT `fk_gasto_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_gasto_categoria_id_categoria` FOREIGN KEY (`categoria_id`) REFERENCES `categoria` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_gasto_monto_positivo` CHECK (monto > 0),
  CONSTRAINT `ck_gasto_fechas_validas` CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio),
  CONSTRAINT `ck_gasto_tipo_frecuencia` CHECK ((tipo = 'variable' AND frecuencia = 'unico') OR (tipo = 'fijo' AND frecuencia <> 'unico'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- T53b: estas columnas guardan el monto CIFRADO (AES-256-GCM, 'v1:...'); ver docs/CIFRADO.md. Sin CHECK de monto: se validan en la API.
CREATE TABLE `tarjeta` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `nombre` VARCHAR(60) NOT NULL,
  `banco` VARCHAR(60) NOT NULL,
  `ultimos_4` CHAR(4) NULL,
  `limite_credito` VARCHAR(96) NOT NULL,
  `saldo_actual` VARCHAR(96) NOT NULL,
  `dia_corte` TINYINT UNSIGNED NOT NULL,
  `dia_pago` TINYINT UNSIGNED NOT NULL,
  `tasa_anual` DECIMAL(5,2) NULL,
  `activa` TINYINT(1) NOT NULL DEFAULT 1,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_tarjeta_usuario_id` (`usuario_id`),
  CONSTRAINT `fk_tarjeta_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_tarjeta_dia_corte_rango` CHECK (dia_corte BETWEEN 1 AND 31),
  CONSTRAINT `ck_tarjeta_dia_pago_rango` CHECK (dia_pago BETWEEN 1 AND 31),
  CONSTRAINT `ck_tarjeta_ultimos_4_digitos` CHECK (ultimos_4 IS NULL OR ultimos_4 REGEXP '^[0-9]{4}$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `estado_cuenta` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tarjeta_id` BIGINT UNSIGNED NOT NULL,
  `periodo_inicio` DATE NOT NULL,
  `fecha_corte` DATE NOT NULL,
  `fecha_limite_pago` DATE NOT NULL,
  `saldo_al_corte` VARCHAR(96) NOT NULL,
  `pago_minimo` VARCHAR(96) NULL,
  `pago_no_intereses` VARCHAR(96) NULL,
  `archivo_ref` VARCHAR(255) NULL,
  `estatus` ENUM('procesando', 'extraido', 'revisado', 'error') NOT NULL DEFAULT 'procesando',
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_estado_cuenta_tarjeta_corte` (`tarjeta_id`, `fecha_corte`),
  CONSTRAINT `fk_estado_cuenta_tarjeta_id_tarjeta` FOREIGN KEY (`tarjeta_id`) REFERENCES `tarjeta` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_estado_cuenta_corte_desde_inicio` CHECK (fecha_corte >= periodo_inicio),
  CONSTRAINT `ck_estado_cuenta_pago_despues_corte` CHECK (fecha_limite_pago > fecha_corte)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `plan_msi` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tarjeta_id` BIGINT UNSIGNED NOT NULL,
  `categoria_id` BIGINT UNSIGNED NULL,
  `descripcion` VARCHAR(120) NOT NULL,
  `monto_original` VARCHAR(96) NOT NULL,
  `num_mensualidades` SMALLINT UNSIGNED NOT NULL,
  `mensualidades_pagadas` SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `monto_mensualidad` VARCHAR(96) NOT NULL,
  `fecha_compra` DATE NOT NULL,
  `estatus` ENUM('activo', 'liquidado', 'cancelado') NOT NULL DEFAULT 'activo',
  `origen` ENUM('extraido', 'manual') NOT NULL,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_plan_msi_tarjeta_id` (`tarjeta_id`),
  KEY `ix_plan_msi_categoria_id` (`categoria_id`),
  CONSTRAINT `fk_plan_msi_tarjeta_id_tarjeta` FOREIGN KEY (`tarjeta_id`) REFERENCES `tarjeta` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_plan_msi_categoria_id_categoria` FOREIGN KEY (`categoria_id`) REFERENCES `categoria` (`id`) ON DELETE SET NULL,
  CONSTRAINT `ck_plan_msi_mensualidades_minimo` CHECK (num_mensualidades >= 2),
  CONSTRAINT `ck_plan_msi_pagadas_en_rango` CHECK (mensualidades_pagadas <= num_mensualidades)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `movimiento` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `estado_cuenta_id` BIGINT UNSIGNED NOT NULL,
  `origen` ENUM('extraido', 'manual') NOT NULL,
  `estado_revision` ENUM('pendiente', 'confirmado', 'corregido', 'descartado') NOT NULL DEFAULT 'pendiente',
  `fecha` DATE NOT NULL,
  `descripcion` VARCHAR(255) NOT NULL,
  `monto` VARCHAR(96) NOT NULL,
  `tipo` ENUM('cargo', 'pago', 'interes', 'comision', 'mensualidad_msi') NOT NULL,
  `categoria_id` BIGINT UNSIGNED NULL,
  `plan_msi_id` BIGINT UNSIGNED NULL,
  `fecha_extraida` DATE NULL,
  `descripcion_extraida` VARCHAR(255) NULL,
  `monto_extraido` VARCHAR(96) NULL,
  `tipo_extraido` ENUM('cargo', 'pago', 'interes', 'comision', 'mensualidad_msi') NULL,
  `confianza` DECIMAL(3,2) NULL,
  `corregido_en` TIMESTAMP NULL DEFAULT NULL,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_movimiento_estado_cuenta_id` (`estado_cuenta_id`),
  KEY `ix_movimiento_categoria_id` (`categoria_id`),
  KEY `ix_movimiento_plan_msi_id` (`plan_msi_id`),
  CONSTRAINT `fk_movimiento_estado_cuenta_id_estado_cuenta` FOREIGN KEY (`estado_cuenta_id`) REFERENCES `estado_cuenta` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_movimiento_categoria_id_categoria` FOREIGN KEY (`categoria_id`) REFERENCES `categoria` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_movimiento_plan_msi_id_plan_msi` FOREIGN KEY (`plan_msi_id`) REFERENCES `plan_msi` (`id`) ON DELETE SET NULL,
  CONSTRAINT `ck_movimiento_manual_sin_extraidos` CHECK (origen <> 'manual' OR (fecha_extraida IS NULL AND descripcion_extraida IS NULL AND monto_extraido IS NULL AND tipo_extraido IS NULL)),
  CONSTRAINT `ck_movimiento_confianza_rango` CHECK (confianza IS NULL OR (confianza >= 0 AND confianza <= 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `deuda` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `nombre` VARCHAR(100) NOT NULL,
  `acreedor` VARCHAR(100) NULL,
  `tipo` ENUM('prestamo_personal', 'credito_auto', 'credito_hipotecario', 'familiar_amigo', 'otro') NOT NULL,
  `monto_original` VARCHAR(96) NOT NULL,
  `saldo_actual` VARCHAR(96) NOT NULL,
  `tasa_anual` DECIMAL(5,2) NULL,
  `pago_mensual` VARCHAR(96) NULL,
  `dia_pago` TINYINT UNSIGNED NULL,
  `fecha_inicio` DATE NULL,
  `estatus` ENUM('activa', 'liquidada') NOT NULL DEFAULT 'activa',
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_deuda_usuario_id` (`usuario_id`),
  CONSTRAINT `fk_deuda_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_deuda_dia_pago_rango` CHECK (dia_pago IS NULL OR dia_pago BETWEEN 1 AND 31)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `score_historial` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `calculado_en` DATETIME NOT NULL,
  `puntaje` SMALLINT UNSIGNED NOT NULL,
  `version_modelo` VARCHAR(20) NOT NULL,
  `componentes` JSON NOT NULL,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_score_historial_usuario_calculado` (`usuario_id`, `calculado_en`),
  CONSTRAINT `fk_score_historial_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_score_historial_puntaje_rango` CHECK (puntaje BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `resumen_mensual` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `periodo` DATE NOT NULL,
  `total_ingresos` DECIMAL(12,2) NOT NULL,
  `total_gastos` DECIMAL(12,2) NOT NULL,
  `total_mensualidades_msi` DECIMAL(12,2) NOT NULL,
  `total_deuda` DECIMAL(12,2) NOT NULL,
  `utilizacion_credito` DECIMAL(5,2) NOT NULL,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_resumen_mensual_usuario_periodo` (`usuario_id`, `periodo`),
  CONSTRAINT `fk_resumen_mensual_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_resumen_mensual_periodo_primer_dia` CHECK (DAYOFMONTH(periodo) = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `alerta` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `regla` VARCHAR(10) NOT NULL,
  `referencia` VARCHAR(60) NOT NULL,
  `severidad` ENUM('atencion','critica') NOT NULL,
  `titulo` VARCHAR(120) NOT NULL,
  `mensaje` VARCHAR(300) NOT NULL,
  `accion` VARCHAR(200) NOT NULL,
  `estado` ENUM('activa','resuelta') NOT NULL DEFAULT 'activa',
  `clave_activa` VARCHAR(80) NULL,
  `disparada_en` DATETIME NOT NULL,
  `leida_en` DATETIME NULL,
  `resuelta_en` DATETIME NULL,
  `notificada_en` DATETIME NULL,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_alerta_usuario_clave_activa` (`usuario_id`, `clave_activa`),
  KEY `ix_alerta_usuario_disparada` (`usuario_id`, `disparada_en`),
  CONSTRAINT `fk_alerta_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `alerta_configuracion` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `usuario_id` BIGINT UNSIGNED NOT NULL,
  `umbral_utilizacion` SMALLINT NOT NULL DEFAULT 70,
  `dias_anticipacion` TINYINT UNSIGNED NOT NULL DEFAULT 3,
  `canal_correo` TINYINT(1) NOT NULL DEFAULT 1,
  `canal_push` TINYINT(1) NOT NULL DEFAULT 0,
  `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `actualizado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_alerta_configuracion_usuario` (`usuario_id`),
  CONSTRAINT `fk_alerta_configuracion_usuario_id_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuario` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_alerta_configuracion_umbral` CHECK (umbral_utilizacion BETWEEN 10 AND 100),
  CONSTRAINT `ck_alerta_configuracion_dias` CHECK (dias_anticipacion BETWEEN 1 AND 15)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;